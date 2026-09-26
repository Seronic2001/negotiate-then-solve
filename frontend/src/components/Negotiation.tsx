import clsx from "clsx";
import { motion } from "framer-motion";
import { ArrowRight, BadgeCheck, CircleSlash, Clock, MapPin, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import { pct } from "../lib/meta";
import type { ConstraintView, DiffRow, MessageView, OfferView } from "../lib/types";
import { Avatar, Badge, TierBadge } from "./ui";

export function ConstraintCard({ c, highlight, index = 0 }: { c: ConstraintView; highlight?: boolean; index?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06 }}
      className={clsx(
        "rounded-xl border bg-panel-2/60 p-3.5 transition-colors",
        highlight ? "border-bad/50 shadow-[0_0_0_3px] shadow-bad/10" : "border-line",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11.5px] text-ink-3">{c.id}</span>
        <TierBadge tier={c.tier} />
        <Badge tone={c.hard ? "bad" : "muted"}>{c.hard ? "hard" : "soft"}</Badge>
        <Badge tone="info">{c.type.replace("_", " ")}</Badge>
      </div>
      <p className="mt-2 text-[13.5px] leading-relaxed">{c.text}</p>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11.5px] text-ink-3">
        {c.owner && <span>owner: {c.owner_name}</span>}
        {c.source.request && <span>from {c.source.request}</span>}
        {c.source.rule && <span>rule: {c.source.rule}</span>}
        {c.justification !== "none" && (
          <span className="flex items-center gap-1">
            <ShieldCheck size={12} /> justification {c.justification} (reason kept private)
          </span>
        )}
      </div>
    </motion.div>
  );
}

/** A grounded explanation: each claim with the facts it cites. Hovering a
 * claim highlights its facts; unsupported claims are struck through. */
export function GroundedExplanation({ m }: { m: MessageView }) {
  const [hover, setHover] = useState<number | null>(null);
  const active = hover !== null ? new Set(m.claims[hover]?.facts ?? []) : null;
  const supported = m.claims.filter((c) => c.supported).length;
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
      <div>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <p className="text-xs font-medium uppercase tracking-wider text-ink-3">Claims</p>
          <Badge tone={m.faithfulness >= 0.999 ? "ok" : "warn"}>
            <BadgeCheck size={12} /> {supported}/{m.claims.length} traced · {pct(m.faithfulness)}
          </Badge>
          <Badge tone="muted">{m.explanation_mode}</Badge>
          {m.leaks.length > 0 && <Badge tone="bad">leak: {m.leaks.join(", ")}</Badge>}
        </div>
        <div className="space-y-1.5">
          {m.claims.map((c, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.04 }}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              className={clsx(
                "cursor-default rounded-lg border px-3 py-2 text-[13px] leading-relaxed transition-colors",
                hover === i ? "border-brand/50 bg-brand/8" : "border-transparent",
                !c.supported && "text-ink-3 line-through decoration-bad/60",
              )}
            >
              {c.text}
              {c.facts.length > 0 && (
                <span className="ml-1.5 inline-flex flex-wrap gap-1 align-middle">
                  {c.facts.map((f) => (
                    <span key={f} className="rounded bg-brand/12 px-1 font-mono text-[10px] text-brand">
                      {f}
                    </span>
                  ))}
                </span>
              )}
            </motion.div>
          ))}
        </div>
      </div>
      <div>
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-3">Facts the explainer may use</p>
        <div className="space-y-1.5">
          {m.facts.map((f) => (
            <div
              key={f.id}
              className={clsx(
                "rounded-lg border px-3 py-2 text-[12.5px] transition-all",
                active?.has(f.id) ? "border-brand bg-brand/10 shadow-md shadow-brand/10" : active ? "border-line opacity-40" : "border-line",
              )}
            >
              <span className="mr-1.5 font-mono text-[10.5px] text-brand">{f.id}</span>
              {f.text}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function OfferCard({
  offer,
  selected,
  onSelect,
  accepted,
}: {
  offer: OfferView;
  selected?: boolean;
  onSelect?: () => void;
  accepted?: boolean;
}) {
  return (
    <motion.button
      type="button"
      whileHover={onSelect ? { y: -3 } : undefined}
      whileTap={onSelect ? { scale: 0.98 } : undefined}
      onClick={onSelect}
      disabled={!onSelect}
      className={clsx(
        "relative w-full overflow-hidden rounded-2xl border p-4 text-left transition-colors",
        selected || accepted ? "border-brand bg-brand/8 shadow-lg shadow-brand/15" : "border-line bg-panel-2/60 hover:border-brand/40",
        !onSelect && "cursor-default",
      )}
    >
      {(selected || accepted) && <motion.div layoutId={accepted ? undefined : "offer-glow"} className="absolute inset-0 bg-gradient-to-br from-brand/10 to-transparent" />}
      <div className="relative flex items-center justify-between">
        <span className={clsx("grid size-8 place-items-center rounded-lg text-sm font-bold", selected || accepted ? "grad-bg text-white" : "bg-panel text-ink-2 ring-1 ring-line")}>
          {offer.key}
        </span>
        {offer.verified ? (
          <Badge tone="ok">
            <ShieldCheck size={12} /> solver-verified
          </Badge>
        ) : (
          <Badge tone="warn">
            <Sparkles size={12} /> LLM-invented
          </Badge>
        )}
      </div>
      <div className="relative mt-3 space-y-2">
        {offer.placements.map((p) => (
          <div key={p.session}>
            <p className="text-[13px] font-medium">{p.session_name}</p>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[12.5px] text-ink-2">
              <span className="flex items-center gap-1">
                <Clock size={12} /> {p.day} {p.time}
              </span>
              <span className="flex items-center gap-1">
                <MapPin size={12} /> {p.room}
              </span>
            </p>
          </div>
        ))}
      </div>
      <div className="relative mt-3 flex items-center gap-3 border-t border-line pt-2.5 text-[11.5px] text-ink-3">
        <span>cost {offer.cost.toFixed(2)}</span>
        <span>moves {offer.moved} class{offer.moved === 1 ? "" : "es"}</span>
        <span className="truncate">relaxes {offer.drop.join(", ")}</span>
      </div>
    </motion.button>
  );
}

export function MessageBubble({ m, reply }: { m: MessageView; reply?: { decision: string | null; choice?: string; text?: string } }) {
  return (
    <div className="space-y-3">
      <div className="flex gap-3">
        <div className="grid size-8 shrink-0 place-items-center rounded-full grad-bg text-white">
          <Sparkles size={15} />
        </div>
        <div className="min-w-0 flex-1 rounded-2xl rounded-tl-md border border-line bg-panel-2/60 p-4">
          <p className="mb-2 text-xs text-ink-3">
            Round {m.round} · to <span className="font-medium text-ink-2">{m.to_name}</span>
          </p>
          <p className="whitespace-pre-line text-[13.5px] leading-relaxed">{m.text.split("\n\nOptions:")[0]}</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            {m.offers.map((o) => (
              <OfferCard key={o.key} offer={o} accepted={reply?.decision === "accept" && reply.choice === o.key} />
            ))}
          </div>
        </div>
      </div>
      {reply && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end gap-3">
          <div className="max-w-[80%] rounded-2xl rounded-tr-md bg-brand/12 px-4 py-3 ring-1 ring-inset ring-brand/25">
            <p className="text-xs text-ink-3">{m.to_name}</p>
            <p className="mt-1 text-[13.5px]">
              {reply.text || (reply.decision === "no_reply" ? "No reply before the deadline." : reply.decision)}
            </p>
            <p className="mt-1.5">
              <Badge tone={reply.decision === "accept" ? "ok" : reply.decision === "counter" ? "warn" : "bad"}>
                {reply.decision === "accept" ? `accepted ${reply.choice}` : reply.decision}
              </Badge>
            </p>
          </div>
          <Avatar name={m.to_name} id={m.to} />
        </motion.div>
      )}
    </div>
  );
}

export function DiffTable({ rows }: { rows: DiffRow[] }) {
  if (!rows.length) {
    return (
      <p className="flex items-center gap-2 py-4 text-sm text-ink-3">
        <CircleSlash size={15} /> No class moves.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-[13px]">
        <thead>
          <tr className="border-b border-line text-left text-[11.5px] uppercase tracking-wider text-ink-3">
            <th className="py-2 pr-3 font-medium">Session</th>
            <th className="py-2 pr-3 font-medium">Teacher</th>
            <th className="py-2 pr-3 font-medium">Before</th>
            <th className="py-2 pr-3" />
            <th className="py-2 font-medium">After</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <motion.tr
              key={r.session}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.03 }}
              className="border-b border-line/60"
            >
              <td className="py-2.5 pr-3">
                <p className="font-medium">{r.session_name.replace(/^the /, "")}</p>
              </td>
              <td className="py-2.5 pr-3 text-ink-2">{r.faculty_name}</td>
              <td className="py-2.5 pr-3 text-ink-3 line-through decoration-bad/50">{r.before ? `${r.before.day} ${r.before.time} · ${r.before.room}` : "—"}</td>
              <td className="py-2.5 pr-3 text-ink-3">
                <ArrowRight size={14} />
              </td>
              <td className="py-2.5 font-medium text-ok">{r.after ? `${r.after.day} ${r.after.time} · ${r.after.room}` : "—"}</td>
            </motion.tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
