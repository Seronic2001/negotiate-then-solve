import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { ChatPanel, type LookupMessage } from "../components/ChatPanel";
import { ActionCard, ClassMenu, intent, sentence, type ActionKind, type Draft } from "../components/ClassActions";
import { TimetableGrid } from "../components/TimetableGrid";
import { WeekStepper } from "../components/WeekStepper";
import { Card, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import type { TimetableEntry } from "../lib/types";

/** The request workspace, the same for every role: the week's timetable first (click a class to cancel, move
 * or swap it, with the free slots shown, or to name it in a message); beside it, one chat with the assistant
 * (components/ChatPanel) for questions about the timetable or the rules and for requests, follow-ups included;
 * the free hours an answer gives are shaded on the timetable. A request's progress is on its page (Requests).
 * Faculty and class representatives have it as their home (it replaces the Inbox for them); everyone else opens
 * it as New request. */
export default function Home() {
  const { user } = useAuth();
  const teaching = ["faculty", "guest_faculty", "hod"].includes(user?.role ?? "");
  const group = user?.role === "student" && user.id.startsWith("ST-") ? user.id.slice(3) : null;

  const { data: inst } = useApi(() => api.instance(), []);
  const { data: cal } = useApi(() => api.calendar(), []);
  const [week, setWeek] = useState<number | null>(null); // null until the calendar is in
  // this person's classes, or every teacher's: someone with no classes of their own (the office, the lab
  // in-charge, the exam cell) starts on every class
  const [scope, setScope] = useState<"mine" | "all">(teaching || group ? "mine" : "all");
  useEffect(() => {
    if (!cal || week !== null) return;
    // at the weekend this week's classes are all over, so open on the next one (nothing can move into the past)
    const w = cal.weeks[cal.current_week - 1];
    const friday = w ? new Date(`${w.monday}T00:00:00`) : null;
    friday?.setDate(friday.getDate() + cal.days.length - 1);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    setWeek(friday && friday < today && cal.current_week < cal.weeks.length ? cal.current_week + 1 : cal.current_week);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cal]);
  const { data: tt } = useApi(() => (week === null ? Promise.resolve(null) : api.timetable({ week })), [week], 5000);
  const shownWeek = week;

  // a class named in the chat's message (its key changes each time), and a nudge to read the chat again
  const [insert, setInsert] = useState<{ text: string; key: number } | null>(null);
  const [poke, setPoke] = useState(0);
  // the timetable beside the chat, or the chat alone: shown unless the person hid it (remembered in this browser)
  const [timetableShown, setTimetableShown] = useState(() => {
    try {
      return localStorage.getItem("home.timetable") !== "hidden";
    } catch {
      return true;
    }
  });
  const showTimetable = (shown: boolean) => {
    setTimetableShown(shown);
    try {
      localStorage.setItem("home.timetable", shown ? "shown" : "hidden");
    } catch {
      // private browsing: remembered for this page only
    }
  };

  const mine = useMemo(
    () => (tt?.entries ?? []).filter((e) => (teaching ? e.faculty === user?.id : group ? e.groups.includes(group) : false)),
    [tt, teaching, group, user],
  );
  // outlined: the classes the cancel, move or swap being put together is about
  // a request being put together by clicks (cancel, move or swap a class), and the menu that starts one
  const [menu, setMenu] = useState<{ x: number; y: number; cls: TimetableEntry } | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [sending, setSending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const outlined = useMemo(
    () => new Set(draft ? [draft.cls.session, ...(draft.theirs ? [draft.theirs.session] : [])] : []),
    [draft],
  );
  const target = draft?.kind === "move" && draft.to?.slot != null && draft.to.day ? { day: draft.to.day, slot: draft.to.slot } : null;
  // while a move is being put together, where it would go (a request's change is shown in its conversation)
  const ghosts = target && draft ? [{ session: draft.cls.session, day: target.day, slot: target.slot, title: `${draft.cls.title} ${draft.cls.kind}`, note: "new time · not sent yet" }] : [];

  // Where a class may go, and which classes it may be swapped with, judged on this week's published
  // timetable: its teacher and its sections must be free, and the lunch hour stays free. Only a hint;
  // the solver checks the rest (rooms, pending changes).
  const all = useMemo(() => tt?.entries ?? [], [tt]);
  const cellsOf = (day: string, slot: number, duration: number) => Array.from({ length: duration }, (_, i) => `${day}:${slot + i}`);
  const busy = (who: (o: TimetableEntry) => boolean, except: string[]) =>
    new Set(all.filter((o) => who(o) && !except.includes(o.session)).flatMap((o) => cellsOf(o.day, o.slot, o.duration)));
  const freeFor = (e: TimetableEntry, cells: string[], except: string[]) => {
    const taken = busy((o) => o.faculty === e.faculty || o.groups.some((g) => e.groups.includes(g)), except);
    return !cells.some((c) => taken.has(c));
  };
  // a day of the shown week that is already over: nothing can be moved there any more
  const dayPassed = (day: string) => {
    const w = week && cal ? cal.weeks[week - 1] : null;
    if (!w || !cal) return false;
    const at = new Date(`${w.monday}T00:00:00`);
    at.setDate(at.getDate() + cal.days.indexOf(day));
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return at < today;
  };
  const weekOver = !!cal && cal.days.every(dayPassed);
  // free hours from a question answered in the chat ("when is Dr. Iyer free this week?"), shaded on that week;
  // any other answer about a week opens that week
  const [shade, setShade] = useState<{ week: number; free: Set<string> } | null>(null);
  const showAnswer = (m: LookupMessage) => {
    const asked = m.call?.week ?? m.view?.week;
    if (asked) setWeek(asked);
    if (!m.call || !m.free) return setShade(null);
    setShade({ week: m.call.week, free: new Set(m.free.map((h) => `${h.day}:${h.slot}`)) });
  };
  const shaded = !draft && !!shade && shade.week === week;
  const slotState = (day: string, slot: number): "free" | "blocked" | null => {
    if (shaded) return shade!.free.has(`${day}:${slot}`) ? "free" : null;
    if (draft?.kind !== "move" || !inst) return null;
    const e = draft.cls;
    if (day === e.day && slot === e.slot) return null; // where it is now
    if (dayPassed(day)) return "blocked";
    const lunch = inst.calendar.lunch_slot;
    const cells = cellsOf(day, slot, e.duration);
    if (slot + e.duration > inst.calendar.slots_per_day || (lunch != null && slot <= lunch && lunch < slot + e.duration)) return "blocked";
    return freeFor(e, cells, [e.session]) ? "free" : "blocked";
  };
  const swappable = useMemo(() => {
    if (draft?.kind !== "swap") return null;
    const e = draft.cls;
    return new Set(
      all
        .filter(
          (o) =>
            o.session !== e.session &&
            o.faculty !== e.faculty &&
            o.duration === e.duration &&
            freeFor(e, cellsOf(o.day, o.slot, o.duration), [e.session, o.session]) &&
            freeFor(o, cellsOf(e.day, e.slot, e.duration), [e.session, o.session]),
        )
        .map((o) => o.session),
    );
  }, [draft, all]); // eslint-disable-line react-hooks/exhaustive-deps
  const dim = swappable ? new Set(all.filter((o) => o.session !== draft!.cls.session && !swappable.has(o.session)).map((o) => o.session)) : undefined;
  // each day's date in the week shown, for the grid's headings
  const dates = useMemo(() => {
    const w = shownWeek ? cal?.weeks[shownWeek - 1] : null;
    if (!w || !cal) return undefined;
    const today = new Date().toDateString();
    return Object.fromEntries(
      cal.days.map((d, i) => {
        const at = new Date(`${w.monday}T00:00:00`);
        at.setDate(at.getDate() + i);
        return [d, { label: at.toLocaleDateString(undefined, { day: "numeric", month: "short" }), today: at.toDateString() === today }];
      }),
    );
  }, [cal, shownWeek]);
  const cancelled = (tt?.cancelled ?? []).filter((c) => mine.some((e) => e.session === c.session) || (group && c.groups.includes(group)));

  const dayName = (d: string) => inst?.day_names[d] ?? d;
  const label = (slot: number) => inst?.slots.find((s) => s.slot === slot)?.label ?? `slot ${slot}`;
  const phrase = (e: TimetableEntry) => {
    const whose = teaching && e.faculty === user?.id ? "my" : !teaching && group && e.groups.includes(group) ? "the" : `${e.faculty_name}'s`;
    return `${whose} ${e.title} ${e.kind} on ${dayName(e.day)} at ${label(e.slot)}`;
  };
  /** The class named in the message being written in the chat ("…(my Data Structures lecture on Monday at 9 am)"). */
  const name = (e: TimetableEntry) => setInsert((x) => ({ text: phrase(e), key: (x?.key ?? 0) + 1 }));
  // clicking a class: in a swap it is the colleague's class; with Ctrl or Shift it is named in the chat; otherwise
  // the menu
  const pickClass = (e: TimetableEntry, ev: MouseEvent) => {
    if (draft && e.session === draft.cls.session) return stopDraft(); // the class again: leave the action
    if (draft?.kind === "swap") {
      if (swappable?.has(e.session)) setDraft({ ...draft, theirs: e });
      return;
    }
    if (draft) return; // choosing a time: classes are not targets
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey) return name(e);
    setMenu({ x: ev.clientX, y: ev.clientY, cls: e });
  };
  /** Leave a cancel, move or swap being put together: the Cancel button, Esc, or clicking its class again. */
  const stopDraft = () => {
    if (draft?.kind === "swap") setScope("mine");
    setDraft(null);
    setActionError(null);
  };
  useEffect(() => {
    if (!draft) return;
    const esc = (ev: KeyboardEvent) => ev.key === "Escape" && stopDraft();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [draft]); // eslint-disable-line react-hooks/exhaustive-deps
  const startAction = (kind: ActionKind | "write") => {
    const cls = menu!.cls;
    setMenu(null);
    if (kind === "write") return name(cls);
    setActionError(null);
    const passed = !!cal && week !== null && week < cal.current_week; // a past week: pick the weeks instead
    setDraft({ kind, cls, to: null, theirs: null, when: { mode: passed ? "pick" : "this", weeks: [] }, hard: true, reason: "" });
    if (kind === "swap") setScope("all"); // a colleague's class is picked among everyone's
  };
  const sendAction = async () => {
    if (!draft || !inst || week === null) return;
    setSending(true);
    setActionError(null);
    try {
      await api.submitForm(sentence(draft, inst, week), intent(draft, week));
      setDraft(null);
      if (draft.kind === "swap") setScope("mine");
      setPoke((n) => n + 1); // its card in the chat (the server adds the request there), at once
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setSending(false);
    }
  };

  return (
    <div
      className={
        timetableShown
          ? "grid gap-4 lg:h-full lg:grid-cols-[minmax(0,1fr)_minmax(300px,27%)]"
          : "mx-auto grid w-full max-w-3xl gap-4 lg:h-full" // the chat alone, as a column of reading width
      }
    >
      {/* hidden, not taken away: the week and what is being put together stay as they are */}
      <div className={timetableShown ? "flex min-h-0 min-w-0 flex-col gap-3" : "hidden"}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          {cal ? (
            <WeekStepper cal={cal} week={shownWeek} onChange={(w) => w !== null && setWeek(w)} compact />
          ) : (
            <Skeleton className="h-8 w-80" />
          )}
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value as "mine" | "all")}
            title="My timetable: your own classes. All classes: every teacher's classes in the department, for the same week."
            className="h-8 w-40 rounded-md border border-line bg-panel px-2.5 text-[13px] outline-none hover:bg-panel-2 focus:border-brand/60"
          >
            {(teaching || group) && <option value="mine">My timetable</option>}
            <option value="all">All classes</option>
          </select>
        </div>
        {cancelled.length > 0 && (
          <p className="rounded-lg border border-bad/40 bg-bad/5 px-4 py-2.5 text-[13px]">
            Not held this week: {cancelled.map((c) => c.session_name.replace(/^the /, "")).join(" · ")}
          </p>
        )}
        <Card className="h-[560px] min-h-0 p-3 lg:h-auto lg:flex-1">
          {!inst || !tt ? (
            <Skeleton className="h-full" />
          ) : scope === "all" ? (
            <div className="h-full overflow-auto">
              <TimetableGrid instance={inst} entries={tt.entries} changed={outlined} onPick={pickClass} dates={dates} ghosts={ghosts} slotState={slotState} onSlot={draft?.kind === "move" ? (day, slot) => setDraft({ ...draft, to: { day, slot } }) : undefined} dim={dim} />
            </div>
          ) : !mine.length ? (
            <p className="px-3 py-16 text-center text-[13.5px] text-ink-3">No classes in the published timetable for this week.</p>
          ) : (
            <TimetableGrid instance={inst} entries={mine} changed={outlined} onPick={pickClass} fill dates={dates} ghosts={ghosts} slotState={slotState} onSlot={draft?.kind === "move" ? (day, slot) => setDraft({ ...draft, to: { day, slot } }) : undefined} />
          )}
        </Card>
        <p className="flex flex-wrap items-center gap-x-2 text-[12px] text-ink-3">
          {draft?.kind === "move"
            ? weekOver
              ? `Week ${week} is over, so there is no free slot left in it: go to a later week to pick the new time.`
              : "Click a green slot for the new time."
            : draft?.kind === "swap"
              ? "Click the colleague's class to swap with. Classes that cannot be swapped are faded."
              : draft
                ? "Fill in the details on the right."
                : shaded
                  ? "Green: the free hours from your question."
                  : "Click a class to cancel, reschedule or swap it."}
          {shaded && (
            <button onClick={() => setShade(null)} className="font-medium text-brand hover:underline">
              Clear
            </button>
          )}
          {draft && (
            <>
              <span>Esc or click the class again to stop.</span>
              <button onClick={stopDraft} className="font-medium text-brand hover:underline">
                Cancel {draft.kind === "move" ? "rescheduling" : draft.kind === "swap" ? "the swap" : "this"}
              </button>
            </>
          )}
        </p>
      </div>

      <Card className="flex h-[560px] min-h-0 flex-col lg:h-full">
        {draft && inst && week !== null && (
          <ActionCard
            d={draft}
            set={setDraft}
            inst={inst}
            week={week}
            weeks={inst.calendar.weeks}
            current={cal?.current_week ?? 1}
            sending={sending}
            error={actionError}
            onCancel={stopDraft}
            onSend={sendAction}
          />
        )}
        {/* kept while a cancel, move or swap is put together (hidden), so a message being written is not lost */}
        <div className={draft ? "hidden" : "flex min-h-0 flex-1 flex-col"}>
          <ChatPanel
            inst={inst ?? null}
            cal={cal ?? null}
            onShow={showAnswer}
            insert={insert}
            poke={poke}
            actions={
              <button
                onClick={() => showTimetable(!timetableShown)}
                className="flex items-center gap-1 text-[11.5px] text-ink-3 hover:text-ink"
                title={timetableShown ? "Hide the timetable: the chat alone" : "Show the timetable beside the chat"}
              >
                {timetableShown ? <PanelLeftClose size={13} /> : <PanelLeftOpen size={13} />}
                {timetableShown ? "Hide timetable" : "Show timetable"}
              </button>
            }
          />
        </div>
      </Card>
      {menu && (
        <ClassMenu at={menu} cls={menu.cls} own={teaching && menu.cls.faculty === user?.id} onPick={startAction} onClose={() => setMenu(null)} />
      )}
    </div>
  );
}
