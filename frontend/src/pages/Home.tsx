import { ArrowRight, BellRing, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ChatPanel } from "../components/ChatPanel";
import { ActionCard, ClassMenu } from "../components/ClassActions";
import { TimetableGrid } from "../components/TimetableGrid";
import { WeekStepper } from "../components/WeekStepper";
import { Card, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { intent, sentence, type ActionKind, type Draft } from "../lib/draft";
import { useApi } from "../lib/hooks";
import { canMoveTo, dayPassed, swappableWith } from "../lib/scheduling";
import type { TimetableEntry } from "../lib/types";
import { useWeek } from "../lib/useWeek";
import { useWorkspace, WorkspaceProvider } from "../lib/workspace";

/** The request workspace, the same for every role: the week's timetable first (click a class to cancel, move
 * or swap it, with the free slots shown, or to name it in a message); beside it, one chat with the assistant
 * (components/ChatPanel) for questions about the timetable or the rules and for requests, follow-ups included;
 * the free hours an answer gives are shaded on the timetable. The two talk through the workspace (lib/workspace),
 * which also opens a request's details or a cited rule beside the chat. A page elsewhere can send a class here to
 * be named in the chat (``state.mention``, e.g. "Ask about this class" on This week). */
export default function Home() {
  return (
    <WorkspaceProvider>
      <Workspace />
    </WorkspaceProvider>
  );
}

/** How the timetable is shown: remembered in this browser. */
function useRemembered(key: string, initial: boolean) {
  const [on, setOn] = useState(() => {
    try {
      const v = localStorage.getItem(key);
      return v === null ? initial : v === "shown";
    } catch {
      return initial;
    }
  });
  const set = (v: boolean) => {
    setOn(v);
    try {
      localStorage.setItem(key, v ? "shown" : "hidden");
    } catch {
      // private browsing: remembered for this page only
    }
  };
  return [on, set] as const;
}

function Workspace() {
  const { user, can } = useAuth();
  const ws = useWorkspace();
  const location = useLocation();
  const navigate = useNavigate();
  const teaching = ["faculty", "guest_faculty", "hod"].includes(user?.role ?? "");
  const group = user?.role === "student" && user.id.startsWith("ST-") ? user.id.slice(3) : null;

  const { inst, cal, week, setWeek, dates, dayName, slotLabel } = useWeek();
  // this person's classes, or every teacher's: someone with no classes of their own (the office, the lab
  // in-charge, the exam cell) starts on every class
  const [scope, setScope] = useState<"mine" | "all">(teaching || group ? "mine" : "all");
  const { data: tt } = useApi(() => (week === null ? Promise.resolve(null) : api.timetable({ week })), [week], 5000);
  const [timetableShown, showTimetable] = useRemembered("home.timetable", true);

  // a class sent here from another page, named in the chat once
  useEffect(() => {
    const mention = (location.state as { mention?: string } | null)?.mention;
    if (!mention) return;
    ws.name(mention);
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, [location.state]); // eslint-disable-line react-hooks/exhaustive-deps

  const all = useMemo(() => tt?.entries ?? [], [tt]);
  const mine = useMemo(
    () => all.filter((e) => (teaching ? e.faculty === user?.id : group ? e.groups.includes(group) : false)),
    [all, teaching, group, user],
  );
  // a request being put together by clicks (cancel, move or swap a class), and the menu that starts one
  const [menu, setMenu] = useState<{ x: number; y: number; cls: TimetableEntry } | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [sending, setSending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  // outlined: the classes the cancel, move or swap being put together is about
  const outlined = useMemo(() => new Set(draft ? [draft.cls.session, ...(draft.theirs ? [draft.theirs.session] : [])] : []), [draft]);
  const target = draft?.kind === "move" && draft.to?.slot != null && draft.to.day ? { day: draft.to.day, slot: draft.to.slot } : null;
  // while a move is being put together, where it would go (a request's change is shown in its conversation)
  const ghosts = target && draft ? [{ session: draft.cls.session, day: target.day, slot: target.slot, title: `${draft.cls.title} ${draft.cls.kind}`, note: "new time · not sent yet" }] : [];

  const weekOver = !!cal && cal.days.every((d) => dayPassed(cal, week, d));
  // free hours from a question answered in the chat ("when is Dr. Iyer free this week?"), shaded on that week;
  // any other answer about a week opens that week
  const [shade, setShade] = useState<{ week: number; free: Set<string> } | null>(null);
  useEffect(() => {
    const m = ws.answer?.m;
    if (!m) return;
    const asked = m.call?.week ?? m.view?.week;
    if (asked) setWeek(asked);
    setShade(m.call && m.free ? { week: m.call.week, free: new Set(m.free.map((h) => `${h.day}:${h.slot}`)) } : null);
  }, [ws.answer?.key]); // eslint-disable-line react-hooks/exhaustive-deps
  const shaded = !draft && !!shade && shade.week === week;
  // where a class may go, judged on this week's published timetable (lib/scheduling: only a hint, the solver
  // checks the rest)
  const slotState = (day: string, slot: number): "free" | "blocked" | null => {
    if (shaded) return shade!.free.has(`${day}:${slot}`) ? "free" : null;
    if (draft?.kind !== "move" || !inst) return null;
    if (day === draft.cls.day && slot === draft.cls.slot) return null; // where it is now
    return canMoveTo(inst, cal, week, all, draft.cls, day, slot) ? "free" : "blocked";
  };
  const swappable = useMemo(() => (draft?.kind === "swap" ? new Set(swappableWith(all, draft.cls).map((o) => o.session)) : null), [draft, all]);
  const dim = swappable ? new Set(all.filter((o) => o.session !== draft!.cls.session && !swappable.has(o.session)).map((o) => o.session)) : undefined;
  const cancelled = (tt?.cancelled ?? []).filter((c) => mine.some((e) => e.session === c.session) || (group && c.groups.includes(group)));

  const phrase = (e: TimetableEntry) => {
    const whose = teaching && e.faculty === user?.id ? "my" : !teaching && group && e.groups.includes(group) ? "the" : `${e.faculty_name}'s`;
    return `${whose} ${e.title} ${e.kind} on ${dayName(e.day)} at ${slotLabel(e.slot)}`;
  };
  // clicking a class: in a swap it is the colleague's class; with Ctrl or Shift it is named in the chat; otherwise
  // the menu
  const pickClass = (e: TimetableEntry, ev: MouseEvent) => {
    if (draft && e.session === draft.cls.session) return stopDraft(); // the class again: leave the action
    if (draft?.kind === "swap") {
      if (swappable?.has(e.session)) setDraft({ ...draft, theirs: e });
      return;
    }
    if (draft) return; // choosing a time: classes are not targets
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey) return ws.name(phrase(e));
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
    if (kind === "write") return ws.name(phrase(cls));
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
      ws.refreshChat(); // its card in the chat (the server adds the request there), at once
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setSending(false);
    }
  };
  const onSlot = draft?.kind === "move" ? (day: string, slot: number) => setDraft({ ...draft, to: { day, slot } }) : undefined;

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
          {cal ? <WeekStepper cal={cal} week={week} onChange={(w) => w !== null && setWeek(w)} compact /> : <Skeleton className="h-8 w-80" />}
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
        {can("approve") && <NeedsYou />}
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
              <TimetableGrid instance={inst} entries={tt.entries} changed={outlined} onPick={pickClass} dates={dates} ghosts={ghosts} slotState={slotState} onSlot={onSlot} dim={dim} />
            </div>
          ) : !mine.length ? (
            <p className="px-3 py-16 text-center text-[13.5px] text-ink-3">No classes in the published timetable for this week.</p>
          ) : (
            <TimetableGrid instance={inst} entries={mine} changed={outlined} onPick={pickClass} fill dates={dates} ghosts={ghosts} slotState={slotState} onSlot={onSlot} />
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
                  : "Click a class to cancel, reschedule or swap it. Ctrl+click names it in the chat."}
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
            inst={inst}
            cal={cal}
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
      {menu && <ClassMenu at={menu} cls={menu.cls} own={teaching && menu.cls.faculty === user?.id} onPick={startAction} onClose={() => setMenu(null)} />}
    </div>
  );
}

/** For the office: how much waits on them (changes to approve, decisions, messages passed to them), and the way
 * to the Inbox where each is acted on. Hidden when nothing waits. */
function NeedsYou() {
  const { data: ov } = useApi(() => api.overview(), [], 5000);
  const n = (ov?.pending_approvals ?? 0) + (ov?.my_decisions ?? 0) + (ov?.my_forwarded ?? 0);
  if (!n) return null;
  return (
    <Link to="/inbox?view=needs" className="flex items-center gap-2.5 rounded-lg border border-warn/40 bg-warn/5 px-4 py-2 text-[13px] hover:bg-warn/10">
      <BellRing size={14} className="text-warn" />
      <span className="flex-1">
        <span className="font-medium">{n}</span> {n === 1 ? "thing waits" : "things wait"} on you
        {ov?.pending_approvals ? ` · ${ov.pending_approvals} to approve` : ""}
      </span>
      <span className="flex items-center gap-1 font-medium text-brand">
        Open <ArrowRight size={13} />
      </span>
    </Link>
  );
}
