import clsx from "clsx";
import { ArrowRight, BookOpen, CalendarSearch, HelpCircle, Info, Send } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { firstSlots, slotsOf, type Slot } from "../../lib/slots";
import type { CalendarView, CaseSummary, ChatMessage, ConfirmAs, InstanceView } from "../../lib/types";
import { useWorkspace, type LookupMessage } from "../../lib/workspace";
import { Button, StatusBadge } from "../ui";
import { CardFrame, Tag, YouBubble } from "./Bubble";

/** The assistant chat's messages, one card per kind (``CHAT_CARDS``): a new kind of message is a new entry
 * there, and every chat that shows ChatMessages draws it the same way. */

export interface ChatContext {
  inst: InstanceView | null;
  cal: CalendarView | null;
  /** an answer is being sent: the cards' buttons wait */
  busy: boolean;
  onConfirm: (n: number, as: ConfirmAs) => void;
  /** the person's requests by number, for the status on a request's card */
  cases: Map<string, CaseSummary>;
}

type Of<K extends ChatMessage["kind"]> = Extract<ChatMessage, { kind: K }>;
type Renderers = { [K in ChatMessage["kind"]]: (m: Of<K>, x: ChatContext) => ReactNode };

export const CHAT_CARDS: Renderers = {
  text: (m) => <YouBubble compact text={m.text} note={m.read_as && `Read as: ${m.read_as}`} />,
  lookup: (m, x) => <LookupCard m={m} inst={x.inst} cal={x.cal} />,
  rule: (m) => <RuleCard answer={m.answer} rules={m.rules} />,
  confirm: (m, x) => <ConfirmCard n={m.n} text={m.part ? m.text : undefined} answered={m.answered} busy={x.busy} onConfirm={x.onConfirm} />,
  request: (m, x) => <RequestCard id={m.case} summary={x.cases.get(m.case)} />,
  other: (m) => <CardFrame label="Assistant">{m.text}</CardFrame>,
};

/** One chat message, drawn by its kind. */
export function ChatMessageView({ m, x }: { m: ChatMessage; x: ChatContext }) {
  const draw = CHAT_CARDS[m.kind] as (m: ChatMessage, x: ChatContext) => ReactNode;
  return <>{draw(m, x)}</>;
}

const SHOWN_SLOTS = 4; // more than this: "Show on the timetable" shows them all

const TONE: Record<Slot["tone"], string> = {
  free: "border-ok/40 bg-ok/8",
  busy: "border-line bg-panel text-ink-3",
  class: "border-brand/40 bg-brand/6",
  cancelled: "border-bad/40 bg-bad/5 line-through decoration-bad/60",
  moved: "border-warn/40 bg-warn/5",
  extra: "border-brand/40 bg-brand/6",
};

/** A timetable answer: the words, then at most 4 slots grouped by date, then "Show on the timetable". */
export function LookupCard({ m, inst, cal }: { m: LookupMessage; inst: InstanceView | null; cal: CalendarView | null }) {
  const { showAnswer } = useWorkspace();
  const answer = m.answer ?? "";
  const groups = m.view && inst && cal ? slotsOf(m.view, inst, cal) : [];
  const { shown, more } = firstSlots(groups, SHOWN_SLOTS);
  // "Dr. Iyer teaches in week 13: Compiler Design practical, Monday 2–4 pm (Lab 3); …": with the slots below,
  // only the lead-in ("Dr. Iyer teaches in week 13."); the slots carry the details
  const lead = shown.length && answer.includes(": ") ? `${answer.slice(0, answer.indexOf(": "))}.` : answer;
  return (
    <CardFrame label="Lookup" icon={CalendarSearch}>
      <p>{lead}</p>
      {shown.length > 0 && (
        <div className="mt-2 space-y-2">
          {shown.map((g) => (
            <div key={g.day}>
              <p className="mb-1 text-[11px] font-medium text-ink-3">{g.date}</p>
              <div className="flex flex-wrap gap-1.5">
                {g.slots.map((s, i) => (
                  <div key={i} className={clsx("rounded-md border px-2 py-0.5 text-[12px]", TONE[s.tone])}>
                    <span className="font-medium">
                      {s.title ? `${s.title} · ` : ""}
                      {s.time}
                    </span>
                    {s.note && <span className="ml-1.5 text-ink-3">{s.note}</span>}
                    {s.sub && <p className="text-[11px] text-ink-3">{s.sub}</p>}
                  </div>
                ))}
              </div>
            </div>
          ))}
          {more > 0 && <p className="text-[11.5px] text-ink-3">and {more} more</p>}
          <button onClick={() => showAnswer(m)} className="inline-flex items-center gap-1 text-[12px] font-medium text-brand hover:underline">
            Show on the timetable <ArrowRight size={13} />
          </button>
        </div>
      )}
    </CardFrame>
  );
}

/** A rule question's answer and every rule it cites; a cited rule opens beside the chat. */
export function RuleCard({ answer, rules }: { answer: string; rules: { id: string; title: string }[] }) {
  const { openRule } = useWorkspace();
  return (
    <CardFrame label="Rule" icon={BookOpen}>
      <p className="whitespace-pre-wrap">{answer}</p>
      {rules.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {rules.map((r) => (
            <Tag key={r.id} title="Read this rule" onClick={() => openRule(r.id)}>
              <span className="font-mono">{r.id}</span> · {r.title}
            </Tag>
          ))}
        </div>
      )}
    </CardFrame>
  );
}

const ANSWERED: Record<ConfirmAs, string> = {
  request: "Sent as a request.",
  question: "Read as a question.",
  cancel: "Not sent.",
};

/** "Send this as a request?": nothing is sent until the person chooses. ``text``: the request part of a message
 * whose questions were answered above it (shown, and no "It's a question": they already were). */
export function ConfirmCard({ n, text, answered, busy, onConfirm }: {
  n: number;
  text?: string;
  answered?: ConfirmAs;
  busy: boolean;
  onConfirm: (n: number, as: ConfirmAs) => void;
}) {
  return (
    <CardFrame label="Request?" icon={HelpCircle} tone={answered ? undefined : "warn"}>
      <p>{text ? "Part of your message looks like a request. Send it to the timetable office?" : "This looks like a request. Send it to the timetable office?"}</p>
      {text && <p className="mt-1.5 border-l-2 border-line pl-2 text-[12px] text-ink-2">{text}</p>}
      {answered ? (
        <p className="mt-1.5 text-[11.5px] text-ink-3">{ANSWERED[answered]}</p>
      ) : (
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Button variant="primary" size="sm" disabled={busy} onClick={() => onConfirm(n, "request")}>
            Send as a request
          </Button>
          {!text && (
            <Button size="sm" disabled={busy} onClick={() => onConfirm(n, "question")}>
              It's a question
            </Button>
          )}
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => onConfirm(n, "cancel")}>
            Cancel
          </Button>
        </div>
      )}
    </CardFrame>
  );
}

/** A sent request, followed live: what it asks, how far it has got, whether it waits on the person; it opens as
 * a conversation, and its details (how the system handled it) open beside the chat. */
export function RequestCard({ id, summary }: { id: string; summary?: CaseSummary }) {
  const { openDetails } = useWorkspace();
  const waits = !!summary && (summary.waits_on_you || summary.status === "clarification_requested");
  return (
    <CardFrame label="Request" icon={Send} tone={waits ? "warn" : undefined}>
      <div className={clsx(!waits && "rounded-lg border border-line px-3 py-2")}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[12px] text-ink-2">{id}</span>
          {summary && <StatusBadge status={summary.status} live={summary.running} />}
        </div>
        {summary?.text && <p className="mt-1 line-clamp-2 text-[12.5px] text-ink-2">{summary.text}</p>}
        {waits && <p className="mt-1 text-[12px] font-medium text-warn">Waiting on your answer</p>}
        <div className="mt-1.5 flex flex-wrap items-center gap-3">
          <Link to={`/requests/${id}`} className="inline-flex items-center gap-1 text-[12px] font-medium text-brand hover:underline">
            {waits ? "Answer it" : "Open request"} <ArrowRight size={13} />
          </Link>
          <button onClick={() => openDetails(id)} className="inline-flex items-center gap-1 text-[12px] text-ink-3 hover:text-ink">
            <Info size={12} /> Details
          </button>
        </div>
      </div>
    </CardFrame>
  );
}
