import clsx from "clsx";
import { ArrowRight, BookOpen, CalendarSearch, Eraser, HelpCircle, Send, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button, Skeleton } from "./ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { chatExamples } from "../lib/examples";
import { useApi } from "../lib/hooks";
import { firstSlots, slotsOf, type Slot } from "../lib/slots";
import type { CalendarView, ChatMessage, ConfirmAs, InstanceView } from "../lib/types";

const SHOWN_SLOTS = 4; // more than this: "Show on the timetable" shows them all

/** A timetable answer in the chat: what the timetable beside it can shade. */
export type LookupMessage = Extract<ChatMessage, { kind: "lookup" }>;

/** The assistant beside the timetable (pages/Home): one chat for questions and requests (CHAT-PLAN.md). A
 * timetable question is answered with the times it is about, shaded on the timetable (``onShow``); a question
 * about the rules with the rules it cites; anything else is offered as a request and sent only when the person
 * confirms. A follow-up ("and Friday?") is read with the messages before it and shown as it was read. Requests
 * made with clicks on the timetable appear here too, as cards that lead to them.
 *
 * ``insert``: words to add to the message being written (a class clicked on the timetable), each time its
 * ``key`` changes; ``poke``: read the chat again now (a request was just sent from the timetable). */
export function ChatPanel({ inst, cal, onShow, insert, poke, actions }: {
  inst: InstanceView | null;
  cal: CalendarView | null;
  onShow?: (m: LookupMessage) => void;
  insert?: { text: string; key: number } | null;
  poke?: number;
  /** buttons for the panel's header (the page's: show or hide the timetable) */
  actions?: React.ReactNode;
}) {
  const { user } = useAuth();
  const teaches = !!user && ["faculty", "hod", "guest_faculty"].includes(user.role);
  // polled, so a request card's status follows its request
  const { data: messages, refresh, loading } = useApi(() => api.chat(), [], 4000);
  const [text, setText] = useState("");
  const [makeup, setMakeup] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [examples, setExamples] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const seen = useRef<number | null>(null); // the newest message already on screen, so only new answers shade
  const shown = useMemo(() => messages ?? [], [messages]);
  const groups = useMemo(() => chatExamples(user, inst), [user, inst]);
  const suggestions = useMemo(() => groups.flatMap((g) => g.items), [groups]);

  // the newest message in view (braces: an effect must return nothing or a clean-up function, and newer
  // browsers' scrollIntoView returns a Promise, which React would then call as one)
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [shown.length]);

  // a new timetable answer is shaded on the timetable beside the chat at once; older ones on "Show"
  useEffect(() => {
    if (!messages) return;
    const newest = messages.length ? messages[messages.length - 1].n : 0;
    if (seen.current !== null && newest > seen.current) {
      const answer = [...messages].reverse().find((m): m is LookupMessage => m.kind === "lookup" && m.n > seen.current!);
      if (answer) onShow?.(answer);
    }
    seen.current = newest;
  }, [messages]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!insert) return;
    setText((t) => (t.trim() ? `${t.trim().replace(/[.!?]$/, "")} (${insert.text})` : insert.text));
    box.current?.focus();
  }, [insert?.key]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (poke) void refresh();
  }, [poke]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (work: () => Promise<unknown>) => {
    setSending(true);
    setError(null);
    try {
      await work();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  };
  const send = () => {
    const t = text.trim();
    if (!t || sending) return;
    void run(async () => {
      await api.chatSend(t, teaches && makeup);
      setText("");
      setExamples(false);
    });
  };
  const confirm = (n: number, as: ConfirmAs) => void run(() => api.chatConfirm(n, as));
  const clear = () => {
    if (window.confirm("Clear the chat? Your requests stay in the Requests tab.")) void run(() => api.chatClear());
  };
  const pick = (ex: string) => {
    setText(ex);
    setExamples(false);
    box.current?.focus();
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <p className="text-[13.5px] font-semibold">Assistant</p>
        <div className="flex items-center gap-3">
          {shown.length > 0 && (
            <button onClick={clear} className="flex items-center gap-1 text-[11.5px] text-ink-3 hover:text-ink" title="Clear the chat (your requests stay)">
              <Eraser size={11} /> Clear
            </button>
          )}
          {actions}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-3">
        {loading && !messages ? (
          <Skeleton className="h-40" />
        ) : !shown.length ? (
          <Welcome groups={groups} onPick={pick} />
        ) : (
          shown.map((m) => (
            <Message key={m.n} m={m} inst={inst} cal={cal} busy={sending} onConfirm={confirm} onShow={onShow} />
          ))
        )}
        <div ref={end} />
      </div>

      <div className="border-t border-line px-3 pb-3 pt-2">
        {examples && suggestions.length > 0 && (
          <ul className="mb-2 max-h-40 space-y-1 overflow-y-auto rounded-lg border border-line bg-panel p-2">
            {suggestions.map((ex) => (
              <li key={ex}>
                <button onClick={() => pick(ex)} className="text-left text-[12.5px] leading-snug text-ink-2 hover:text-brand">
                  “{ex}”
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-end gap-2 rounded-xl border border-line bg-panel px-3 py-2 focus-within:border-brand/60">
          <textarea
            ref={box}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={2}
            placeholder="Ask or request something…"
            title="Enter to send · Shift+Enter for a new line"
            className="max-h-40 min-h-[2.5rem] flex-1 resize-none bg-transparent py-1 text-[13.5px] leading-relaxed outline-none placeholder:text-ink-3"
          />
          <Button variant="primary" size="sm" icon={Send} loading={sending} disabled={!text.trim()} onClick={send} aria-label="Send" />
        </div>
        <div className="mt-1 flex flex-wrap items-center justify-between gap-2 px-1 text-[11px] text-ink-3">
          <p>
            {shown.length > 0 && suggestions.length > 0 && (
              <button onClick={() => setExamples((x) => !x)} className="flex items-center gap-0.5 hover:text-ink">
                <Sparkles size={11} /> Examples
              </button>
            )}
          </p>
          {teaches && (
            <label className="flex cursor-pointer items-center gap-1.5" title="If you are away in some weeks: ticked, the classes you miss move to other times that week; left empty, they are cancelled">
              <input type="checkbox" checked={makeup} onChange={(e) => setMakeup(e.target.checked)} className="accent-brand" />
              Hold make-up classes
            </label>
          )}
        </div>
        {error && <p className="mt-1 text-[12.5px] text-bad">{error}</p>}
      </div>
    </div>
  );
}

const GROUP_ICON: Record<string, typeof BookOpen> = { Timetable: CalendarSearch, Rules: BookOpen, Requests: Send };

/** The empty chat: one line, then examples of each kind to start from. */
function Welcome({ groups, onPick }: { groups: { title: string; items: string[] }[]; onPick: (ex: string) => void }) {
  return (
    <div className="space-y-4 py-2">
      <div>
        <p className="text-[14px] font-medium">What would you like to know or change?</p>
        <p className="mt-1 text-[12px] text-ink-3">
          Ask about the timetable or the rules, or make a request. A request is sent only after you confirm it. Click a class
          on the timetable to cancel, move or swap it.
        </p>
      </div>
      {groups.map((g) => {
        const Icon = GROUP_ICON[g.title] ?? Sparkles;
        return (
          <div key={g.title} className="space-y-1.5">
            <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-ink-3">
              <Icon size={12} /> {g.title}
            </p>
            {g.items.map((ex) => (
              <button
                key={ex}
                onClick={() => onPick(ex)}
                className="block w-full rounded-lg border border-line bg-panel px-3 py-1.5 text-left text-[12.5px] leading-snug text-ink-2 transition-colors hover:border-brand/50 hover:text-ink"
              >
                {ex}
              </button>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function Message(props: {
  m: ChatMessage;
  inst: InstanceView | null;
  cal: CalendarView | null;
  busy: boolean;
  onConfirm: (n: number, as: ConfirmAs) => void;
  onShow?: (m: LookupMessage) => void;
}) {
  const { m } = props;
  if (m.role === "you")
    return (
      <div className="flex flex-col items-end gap-0.5">
        <p className="max-w-[90%] whitespace-pre-wrap rounded-lg rounded-br-sm bg-brand/12 px-3 py-2 text-[13px]">{m.text}</p>
        {m.read_as && <p className="max-w-[90%] text-[11px] text-ink-3">Read as: {m.read_as}</p>}
      </div>
    );
  if (m.kind === "lookup") return <LookupCard m={m} inst={props.inst} cal={props.cal} onShow={props.onShow} />;
  if (m.kind === "rule") return <RuleCard answer={m.answer} rules={m.rules} />;
  if (m.kind === "confirm") return <ConfirmCard n={m.n} answered={m.answered} busy={props.busy} onConfirm={props.onConfirm} />;
  if (m.kind === "request") return <RequestCard id={m.case} />;
  return <Card label="Assistant">{m.text}</Card>;
}

/** An assistant card: a small label, then the content. */
function Card({ label, icon: Icon, children, tone }: { label: string; icon?: typeof BookOpen; children: React.ReactNode; tone?: "warn" }) {
  return (
    <div className={clsx(tone === "warn" && "rounded-lg border border-warn/40 px-3 py-2")}>
      <p className="mb-1 flex items-center gap-1 text-[11px] text-ink-3">
        {Icon && <Icon size={12} />} {label}
      </p>
      <div className="text-[13px] leading-relaxed">{children}</div>
    </div>
  );
}

const TONE: Record<Slot["tone"], string> = {
  free: "border-ok/40 bg-ok/8",
  busy: "border-line bg-panel text-ink-3",
  class: "border-brand/40 bg-brand/6",
  cancelled: "border-bad/40 bg-bad/5 line-through decoration-bad/60",
  moved: "border-warn/40 bg-warn/5",
  extra: "border-brand/40 bg-brand/6",
};

/** A timetable answer: the words, then at most 4 slots grouped by date, then "Show on the timetable". */
function LookupCard({ m, inst, cal, onShow }: {
  m: LookupMessage;
  inst: InstanceView | null;
  cal: CalendarView | null;
  onShow?: (m: LookupMessage) => void;
}) {
  const answer = m.answer ?? "";
  const groups = m.view && inst && cal ? slotsOf(m.view, inst, cal) : [];
  const { shown, more } = firstSlots(groups, SHOWN_SLOTS);
  // "Dr. Iyer teaches in week 13: Compiler Design practical, Monday 2–4 pm (Lab 3); …": with the slots below,
  // only the lead-in ("Dr. Iyer teaches in week 13."); the slots carry the details
  const lead = shown.length && answer.includes(": ") ? `${answer.slice(0, answer.indexOf(": "))}.` : answer;
  return (
    <Card label="Lookup" icon={CalendarSearch}>
      <p>{lead}</p>
      {shown.length > 0 && (
        <div className="mt-2 space-y-2">
          {shown.map((g) => (
            <div key={g.day}>
              <p className="mb-1 text-[11px] font-medium text-ink-3">{g.date}</p>
              <div className="flex flex-wrap gap-1.5">
                {g.slots.map((s, i) => (
                  <div key={i} className={clsx("rounded-md border px-2 py-0.5 text-[12px]", TONE[s.tone])}>
                    <span className="font-medium">{s.title ? `${s.title} · ` : ""}{s.time}</span>
                    {s.note && <span className="ml-1.5 text-ink-3">{s.note}</span>}
                    {s.sub && <p className="text-[11px] text-ink-3">{s.sub}</p>}
                  </div>
                ))}
              </div>
            </div>
          ))}
          {more > 0 && <p className="text-[11.5px] text-ink-3">and {more} more</p>}
          {onShow && (
            <button onClick={() => onShow(m)} className="inline-flex items-center gap-1 text-[12px] font-medium text-brand hover:underline">
              Show on the timetable <ArrowRight size={13} />
            </button>
          )}
        </div>
      )}
    </Card>
  );
}

/** A rule question's answer and every rule it cites; no dates, no link. */
function RuleCard({ answer, rules }: { answer: string; rules: { id: string; title: string }[] }) {
  return (
    <Card label="Rule" icon={BookOpen}>
      <p className="whitespace-pre-wrap">{answer}</p>
      {rules.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-[11.5px] text-ink-3">
          {rules.map((r) => (
            <li key={r.id}>
              <span className="font-mono text-[11px] text-ink-2">{r.id}</span> · {r.title}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const ANSWERED: Record<ConfirmAs, string> = {
  request: "Sent as a request.",
  question: "Read as a question.",
  cancel: "Not sent.",
};

/** "Send this as a request?": nothing is sent until the person chooses. */
function ConfirmCard({ n, answered, busy, onConfirm }: { n: number; answered?: ConfirmAs; busy: boolean; onConfirm: (n: number, as: ConfirmAs) => void }) {
  return (
    <Card label="Request?" icon={HelpCircle} tone={answered ? undefined : "warn"}>
      <p>This looks like a request. Send it to the timetable office?</p>
      {answered ? (
        <p className="mt-1.5 text-[11.5px] text-ink-3">{ANSWERED[answered]}</p>
      ) : (
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Button variant="primary" size="sm" disabled={busy} onClick={() => onConfirm(n, "request")}>
            Send as a request
          </Button>
          <Button size="sm" disabled={busy} onClick={() => onConfirm(n, "question")}>
            It's a question
          </Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => onConfirm(n, "cancel")}>
            Cancel
          </Button>
        </div>
      )}
    </Card>
  );
}

/** A sent request: its number and the way to it. What happens to it next (questions back, options, the outcome)
 * is on its page in the Requests tab. */
function RequestCard({ id }: { id: string }) {
  return (
    <Card label="Request">
      <p className="font-medium">Request {id}</p>
      <Link to={`/requests/${id}`} className="mt-1 inline-flex items-center gap-1 text-[12px] font-medium text-brand hover:underline">
        Open request <ArrowRight size={13} />
      </Link>
    </Card>
  );
}
