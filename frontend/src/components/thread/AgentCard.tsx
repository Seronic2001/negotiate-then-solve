import clsx from "clsx";
import { Bot, Check, ChevronRight, CircleAlert, Hourglass, MessageCircleQuestion, Square, X } from "lucide-react";
import { useState } from "react";
import type { AgentReply, AgentStep, CaseSummary } from "../../lib/types";
import { LiveDot } from "../ui";
import { CardFrame, Tag } from "./Bubble";

/** The agent's reply in the chat (web/agentic.py): its work folded into one line (open it for every step), then
 * the answer; a question back with answers to pick; what it waits for; the change it sent to the timetable office,
 * as the request card every chat shows. */

/** Each tool, in the words the chat uses for it. */
const TOOL_WORDS: Record<string, string> = {
  find: "Looked up a name",
  describe: "Read about the department",
  classes_of: "Read the classes",
  free_hours: "Found the free hours",
  who_is_free: "Checked who is free",
  free_rooms: "Found the free rooms",
  changes: "Read the changes so far",
  rules: "Searched the rules",
  constrain: "Drafted a rule",
  move_class: "Drafted a move",
  retract: "Took a drafted rule back",
  list_draft: "Read the draft",
  swap_classes: "Drafted a swap",
  cancel_class: "Drafted a cancellation",
  add_class: "Drafted an extra class",
  limit_hours: "Drafted a limit on hours",
  book_room: "Drafted a room booking",
  move_to_window: "Drafted a move into a window",
  limit_load: "Drafted a limit on the load",
  relate_classes: "Drafted how classes relate",
  choose: "Drafted a choice",
  set_weeks: "Set the weeks",
  check_draft: "Checked the draft with the solver",
  ask_requester: "Asked you",
  make_offer: "Asked a colleague",
  message_party: "Told someone",
  submit: "Sent it to the timetable office",
  decline: "Declined",
  escalate: "Passed it to the timetable office",
};

const UNFINISHED: Record<string, string> = {
  model_error: "The assistant could not be reached.",
  budget_exhausted: "The assistant ran out of steps.",
  stuck: "The assistant went round in circles.",
  interrupted: "The server restarted while the assistant worked on this.",
  not_committed: "The timetable changed before it could be approved.",
};

export interface AgentContext {
  busy: boolean;
  /** an answer picked from the question's options: sent as the person's next message */
  onSend: (text: string) => void;
  onStop: (episode: string) => void;
  /** the request card of a case the reply became */
  requestCard: (id: string, summary?: CaseSummary) => React.ReactNode;
  cases: Map<string, CaseSummary>;
}

export function AgentCard({ m, x }: { m: AgentReply & { n: number }; x: AgentContext }) {
  const p = m.pending;
  const asksYou = !!p && p.to_requester;
  const label = m.busy ? "Assistant · working" : asksYou ? "Assistant · a question for you" : "Assistant";
  return (
    <CardFrame
      label={label}
      icon={Bot}
      tone={asksYou ? "warn" : undefined}
      action={
        m.busy && (
          <button
            onClick={() => x.onStop(m.episode)}
            title="Stop: nothing it does after this reaches the timetable office"
            className="flex items-center gap-1 rounded px-1 py-0.5 text-[11px] text-ink-3 hover:bg-panel-2 hover:text-bad"
          >
            <Square size={10} className="fill-current" /> Stop
          </button>
        )
      }
    >
      <Thinking steps={m.steps} busy={m.busy} />
      {m.latest && <Outcome m={m} x={x} />}
    </CardFrame>
  );
}

/** The answer and what follows from it: a question back, a wait, the draft sent for approval, an error. */
function Outcome({ m, x }: { m: AgentReply; x: AgentContext }) {
  const p = m.pending;
  const failed = UNFINISHED[m.status];
  return (
    <div className="space-y-2">
      {m.text && !p && <p className="whitespace-pre-wrap">{m.text}</p>}
      {p && p.to_requester && (
        <div>
          <p className="flex items-start gap-1.5 whitespace-pre-wrap">
            <MessageCircleQuestion size={14} className="mt-0.5 shrink-0 text-warn" />
            {p.text}
          </p>
          {m.options.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1">
              {m.options.map((o) => (
                <Tag key={o} title="Answer with this" onClick={x.busy ? undefined : () => x.onSend(o)}>
                  {o}
                </Tag>
              ))}
            </div>
          ) : null}
          <p className="mt-1.5 text-[11.5px] text-ink-3">Answer in the box below.</p>
        </div>
      )}
      {p && !p.to_requester && (
        <div className="rounded-lg border border-info/30 bg-info/5 px-3 py-2">
          <p className="flex items-center gap-1.5 text-[11.5px] font-medium text-info">
            <Hourglass size={12} /> Waiting for {p.to_name} to answer
          </p>
          <p className="mt-1 whitespace-pre-wrap text-[12.5px] text-ink-2">{p.text}</p>
          {p.rule && <p className="mt-1 text-[12px] text-ink-3">Their rule: {p.rule}</p>}
        </div>
      )}
      {m.status === "submitted" && m.draft.length > 0 && (
        <div className="rounded-lg border border-line px-3 py-2">
          <p className="text-[11.5px] font-medium text-ink-3">The change, checked by the solver</p>
          <ul className="mt-1 space-y-0.5">
            {m.draft.map((d) => (
              <li key={d} className="flex gap-1.5 text-[12.5px] text-ink-2">
                <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-brand/60" /> {d}
              </li>
            ))}
          </ul>
        </div>
      )}
      {m.status === "stopped" && <p className="text-[12.5px] text-ink-3">Stopped. Nothing was sent to the timetable office.</p>}
      {failed && (
        <p className="flex items-start gap-1.5 rounded-md bg-bad/8 px-2.5 py-1.5 text-[12.5px] text-bad">
          <CircleAlert size={14} className="mt-0.5 shrink-0" />
          <span>
            {failed} Nothing was changed; send it again.
            {m.detail && <span className="mt-0.5 block text-[11.5px] opacity-80">{m.detail}</span>}
          </span>
        </p>
      )}
      {m.case && x.requestCard(m.case, x.cases.get(m.case))}
    </div>
  );
}

/** The agent's work in one line ("Thinking…" while it works, "Worked through 5 steps · 3 s" after); open it for
 * every step: what the model thought between tools, each tool with what came back, each question and its answer. */
/** ``defaultOpen``: every step shown to start with (a request's page). */
export function Thinking({ steps, busy, defaultOpen = false }: { steps: AgentStep[]; busy: boolean; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const shown = steps.filter((s) => !(s.type === "model" && !s.calls.length) && s.type !== "end" && s.type !== "waiting");
  const tools = steps.filter((s) => s.type === "tool").length;
  const ms = steps.reduce((t, s) => t + ("ms" in s && s.ms ? s.ms : 0), 0);
  if (!busy && !shown.length) return null;
  const line = busy
    ? shown.length
      ? `Thinking… ${describe(shown[shown.length - 1])}`
      : "Thinking…"
    : `Worked through ${tools} ${tools === 1 ? "step" : "steps"}${ms > 0 ? ` · ${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s` : ""}`;
  return (
    <div className="mb-1.5">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex max-w-full items-center gap-1.5 text-left text-[12px] text-ink-3 hover:text-ink"
        aria-expanded={open}
      >
        {busy ? <LiveDot tone="info" /> : <ChevronRight size={12} className={clsx("shrink-0 transition-transform", open && "rotate-90")} />}
        <span className="truncate">{line}</span>
      </button>
      {open && shown.length > 0 && (
        <ol className="mt-1.5 space-y-1 border-l border-line pl-3">
          {shown.map((s, i) => (
            <StepRow key={i} s={s} />
          ))}
        </ol>
      )}
    </div>
  );
}

function describe(s: AgentStep): string {
  if (s.type === "tool") return TOOL_WORDS[s.name] ?? s.name;
  if (s.type === "reply") return s.kind === "question" ? "asked you" : `asked ${s.to}`;
  if (s.type === "model") return s.calls.map((c) => TOOL_WORDS[c] ?? c).join(", ");
  return "";
}

function StepRow({ s }: { s: AgentStep }) {
  if (s.type === "model")
    return s.text ? <li className="text-[12px] italic leading-snug text-ink-3">{s.text}</li> : null;
  if (s.type === "tool")
    return (
      <li className="text-[12px] leading-snug" title={s.result}>
        <span className="flex items-center gap-1.5">
          {s.ok ? <Check size={12} className="shrink-0 text-ok" /> : <X size={12} className="shrink-0 text-bad" />}
          <span className={s.ok ? "text-ink-2" : "text-bad"}>{TOOL_WORDS[s.name] ?? s.name}</span>
          <span className="font-mono text-[10.5px] text-ink-3">{s.name}</span>
        </span>
        {!s.ok && <span className="mt-0.5 block pl-[18px] text-[11.5px] text-bad/80">{s.result}</span>}
      </li>
    );
  if (s.type === "reply")
    return (
      <li className="text-[12px] leading-snug text-ink-2">
        <span className="text-ink-3">{s.kind === "question" ? "Asked you" : `Asked ${s.to}`}:</span> {s.text}
        <span className="mt-0.5 block text-ink-3">
          Answer: {s.says || s.answer}
        </span>
      </li>
    );
  if (s.type === "decision")
    return <li className="text-[12px] text-ink-2">{s.approved ? "Approved by the timetable office" : `Not approved${s.note ? `: ${s.note}` : ""}`}</li>;
  if (s.type === "note") return <li className="text-[12px] text-ink-2">The timetable office wrote: {s.text}</li>;
  if (s.type === "model_error") return <li className="text-[12px] text-bad">The model did not answer: {s.error}</li>;
  return null;
}
