import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import { Check } from "lucide-react";
import { Link } from "react-router-dom";
import { ago, clock, EVENT_LABEL, STATUS, TONE_CLASS } from "../lib/meta";
import type { EventRow, Status } from "../lib/types";
import { LiveDot } from "./ui";

const MAIN: { status: Status; short: string }[] = [
  { status: "received", short: "Received" },
  { status: "classified", short: "Classified" },
  { status: "policy_checked", short: "Policy" },
  { status: "compiled", short: "Compiled" },
  { status: "solved", short: "Solved" },
  { status: "negotiating", short: "Negotiation" },
  { status: "fairness_audited", short: "Fairness" },
  { status: "awaiting_approval", short: "Approval" },
  { status: "published", short: "Published" },
];
const EXITS: Status[] = ["refused", "denied", "clarification_requested", "escalated", "answered", "forwarded"];

/** The request lifecycle (proposal Figure 2), lit up from the event log. */
export function Lifecycle({ events, status, live }: { events: EventRow[]; status: Status; live?: boolean }) {
  const seen = new Set(events.map((e) => e.kind));
  const reached = MAIN.map((m) => seen.has(m.status) || (m.status === "received" && events.length > 0));
  const skippedNegotiation = seen.has("fairness_audited") && !seen.has("negotiating");
  const last = MAIN.reduce((acc, _m, i) => (reached[i] ? i : acc), 0);
  const exit = EXITS.find((x) => seen.has(x));
  const exitMeta = exit ? STATUS[exit] : null;

  return (
    <div className="relative">
      <div className="flex items-start gap-0 overflow-x-auto pb-2">
        {MAIN.map((m, i) => {
          const done = reached[i];
          const skipped = m.status === "negotiating" && skippedNegotiation;
          const current = i === last && !STATUS[status]?.terminal && live;
          return (
            <div key={m.status} className="flex min-w-[88px] flex-1 flex-col items-center">
              <div className="relative flex w-full items-center">
                <div className={clsx("h-0.5 flex-1", i === 0 ? "opacity-0" : "bg-line")}>
                  {i > 0 && (
                    <motion.div
                      className="h-full grad-bg"
                      initial={{ width: 0 }}
                      animate={{ width: done ? "100%" : 0 }}
                      transition={{ delay: i * 0.08, duration: 0.4 }}
                    />
                  )}
                </div>
                <motion.div
                  initial={{ scale: 0.6, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ delay: i * 0.08, type: "spring", stiffness: 400, damping: 22 }}
                  className={clsx(
                    "relative grid size-8 shrink-0 place-items-center rounded-full border-2 text-[11px] font-semibold",
                    done && !skipped ? "border-transparent grad-bg text-white shadow-lg shadow-brand/30" : "border-line bg-panel text-ink-3",
                    skipped && "border-dashed",
                  )}
                >
                  {current && <span className="absolute inset-0 rounded-full bg-brand animate-pulse-ring" />}
                  {done && !skipped ? <Check size={14} strokeWidth={3} /> : i + 1}
                </motion.div>
                <div className={clsx("h-0.5 flex-1", i === MAIN.length - 1 ? "opacity-0" : "bg-line")}>
                  {i < MAIN.length - 1 && (
                    <motion.div
                      className="h-full grad-bg"
                      initial={{ width: 0 }}
                      animate={{ width: reached[i + 1] ? "100%" : 0 }}
                      transition={{ delay: i * 0.08 + 0.04, duration: 0.4 }}
                    />
                  )}
                </div>
              </div>
              <p className={clsx("mt-2 text-center text-[11.5px] font-medium", done && !skipped ? "text-ink" : "text-ink-3")}>
                {m.short}
                {skipped && <span className="block text-[10px] font-normal">not needed</span>}
              </p>
            </div>
          );
        })}
      </div>
      <AnimatePresence>
        {exitMeta && exit && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            className={clsx("mt-3 flex items-center gap-2 rounded-xl px-3 py-2 text-[13px] ring-1 ring-inset", TONE_CLASS[exitMeta.tone].bg, TONE_CLASS[exitMeta.tone].ring)}
          >
            <exitMeta.icon size={15} className={TONE_CLASS[exitMeta.tone].text} />
            <span className="font-medium">Safe exit: {exitMeta.label}</span>
            <span className="text-ink-3">— the request left the pipeline here, before anything reached the timetable.</span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

const DETAIL_KEYS = ["route", "action", "verdict", "reason", "to", "version", "approver", "rounds", "constraints", "superseded", "moved", "cited", "obligations", "seconds", "solver_seconds", "gini_after"];

function detail(e: EventRow): string {
  const parts: string[] = [];
  for (const k of DETAIL_KEYS) {
    const v = e[k];
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length)) continue;
    parts.push(`${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(", ") : typeof v === "number" ? +v.toFixed(3) : String(v)}`);
  }
  if (e.kind === "negotiation_message" && e.message && typeof e.message === "object") {
    const m = e.message as { to: string; offers: unknown[] };
    parts.push(`to ${m.to} with ${m.offers.length} option(s)`);
  }
  if (e.kind === "negotiation_reply" && e.reply && typeof e.reply === "object") {
    const r = e.reply as { decision: string; choice?: string };
    parts.push(`${r.decision}${r.choice ? ` ${r.choice}` : ""}`);
  }
  if (e.kind === "negotiation_conflict" && Array.isArray(e.mus)) parts.push(`MUS: ${(e.mus as string[]).join(", ")}`);
  return parts.join(" · ");
}

/** Every event for a request, with the time spent between them. */
export function EventTimeline({ events }: { events: EventRow[] }) {
  return (
    <ol className="relative space-y-0">
      {events.map((e, i) => {
        const prev = events[i - 1];
        const dt = prev ? (new Date(e.at).getTime() - new Date(prev.at).getTime()) / 1000 : 0;
        const meta = STATUS[e.kind as Status];
        const tone = e.kind === "error" ? "bad" : meta?.tone ?? (e.kind.startsWith("negotiation") ? "warn" : "info");
        return (
          <motion.li
            key={e.n}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: Math.min(i * 0.03, 0.6) }}
            className="relative flex gap-4 pb-4 pl-1"
          >
            {i < events.length - 1 && <span className="absolute left-[11px] top-6 h-full w-px bg-line" />}
            <span className={clsx("relative mt-1 grid size-[22px] shrink-0 place-items-center rounded-full ring-4 ring-panel", TONE_CLASS[tone].bg)}>
              <span className={clsx("size-2 rounded-full", TONE_CLASS[tone].dot)} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <p className="text-[13.5px] font-medium">{EVENT_LABEL[e.kind] ?? e.kind}</p>
                <span className="font-mono text-[11px] text-ink-3">{clock(e.at)}</span>
                {dt > 0.05 && <span className="rounded-md bg-panel-2 px-1.5 font-mono text-[10.5px] text-ink-3">+{dt.toFixed(2)}s</span>}
              </div>
              {detail(e) && <p className="mt-0.5 break-words text-[12.5px] text-ink-3">{detail(e)}</p>}
            </div>
          </motion.li>
        );
      })}
    </ol>
  );
}

export function ActivityFeed({ events, compact }: { events: EventRow[]; compact?: boolean }) {
  return (
    <div className="space-y-1">
      <AnimatePresence initial={false}>
        {[...events].reverse().map((e) => {
          const meta = STATUS[e.kind as Status];
          const tone = e.kind === "error" ? "bad" : meta?.tone ?? (e.kind.startsWith("negotiation") ? "warn" : "info");
          return (
            <motion.div
              key={e.n}
              layout
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-3 rounded-xl px-2 py-1.5 hover:bg-panel-2"
            >
              <span className={clsx("size-1.5 shrink-0 rounded-full", TONE_CLASS[tone].dot)} />
              <span className="min-w-0 flex-1 truncate text-[13px]">
                <span className="font-medium">{EVENT_LABEL[e.kind] ?? e.kind}</span>
                {!compact && detail(e) && <span className="text-ink-3"> · {detail(e)}</span>}
              </span>
              {e.case && (
                <Link to={`/requests/${e.case}`} className="shrink-0 font-mono text-[11px] text-brand hover:underline">
                  {e.case}
                </Link>
              )}
              <span className="w-16 shrink-0 text-right text-[11px] text-ink-3">{ago(e.at)}</span>
            </motion.div>
          );
        })}
      </AnimatePresence>
      {!events.length && (
        <p className="flex items-center gap-2 px-2 py-6 text-sm text-ink-3">
          <LiveDot tone="muted" /> Waiting for activity…
        </p>
      )}
    </div>
  );
}
