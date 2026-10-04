import clsx from "clsx";
import { ArrowRight, BadgeCheck, Check, CircleSlash, Clock, MapPin, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { pct } from "../lib/meta";
import type { ConstraintView, DiffRow, MessageView, OfferView } from "../lib/types";
import { Avatar, Badge, Mark, TierBadge } from "./ui";

export function ConstraintCard({ c, highlight, index = 0 }: { c: ConstraintView; highlight?: boolean; index?: number }) {
  return (
    <div data-index={index} className={clsx("rounded-md border p-3.5", highlight ? "border-bad/35 bg-bad/[0.04]" : "border-line bg-panel")}>
      <div className="flex flex-wrap items-center gap-2">
        <TierBadge tier={c.tier} />
        <Badge tone={c.hard ? "bad" : "muted"}>{c.hard ? "required" : "if possible"}</Badge>
      </div>
      <p className="mt-2 text-[13.5px] leading-relaxed">{c.text}</p>
      {c.tier_who && <p className="mt-1 text-[12.5px] text-ink-3">Who can change it: {c.tier_who.charAt(0).toLowerCase() + c.tier_who.slice(1)}.</p>}
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11.5px] text-ink-3">
        {c.owner && <span>owner: {c.owner_name}</span>}
        {c.source.request && <span>from {c.source.request}</span>}
        <span className="font-mono opacity-70">{c.id}</span>
        {c.source.rule && <span>rule: {c.source.rule}</span>}
        {c.justification !== "none" && (
          <span className="flex items-center gap-1">
            <ShieldCheck size={12} /> justification {c.justification} (reason kept private)
          </span>
        )}
      </div>
    </div>
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
            <div
              key={i}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              className={clsx(
                "cursor-default rounded-md border px-3 py-2 text-[13px] leading-relaxed transition-colors",
                hover === i ? "border-brand/40 bg-brand/[0.06]" : "border-transparent",
                !c.supported && "text-ink-3 line-through decoration-bad/60",
              )}
            >
              {c.text}
              {c.facts.length > 0 && (
                <span className="ml-1.5 inline-flex flex-wrap gap-1 align-middle">
                  {c.facts.map((f) => (
                    <span key={f} className="rounded bg-panel-2 px-1 font-mono text-[10px] text-ink-3">
                      {f}
                    </span>
                  ))}
                </span>
              )}
            </div>
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
                "rounded-md border px-3 py-2 text-[12.5px] transition-opacity",
                active?.has(f.id) ? "border-brand/50 bg-brand/[0.06]" : active ? "border-line opacity-40" : "border-line",
              )}
            >
              <span className="mr-1.5 font-mono text-[10.5px] text-ink-3">{f.id}</span>
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
  const on = selected || accepted;
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={!onSelect}
      className={clsx(
        "w-full rounded-md border p-3.5 text-left transition-colors",
        on ? "border-brand bg-brand/[0.06]" : "border-line bg-panel",
        onSelect ? "hover:border-brand/60" : "cursor-default",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-[13px] font-semibold">
          <span className={clsx("grid size-5 place-items-center rounded-full border text-[11px]", on ? "border-brand bg-brand text-panel" : "border-line text-ink-2")}>
            {accepted ? <Check size={11} strokeWidth={3} /> : offer.key}
          </span>
          Option {offer.key}
        </span>
        {offer.verified ? (
          <span className="flex items-center gap-1 text-[11.5px] text-ok">
            <ShieldCheck size={12} /> checked by solver
          </span>
        ) : (
          <span className="text-[11.5px] text-warn">invented by the LLM</span>
        )}
      </div>
      <div className="mt-2.5 space-y-2">
        {offer.placements.map((p) => (
          <div key={p.session}>
            <p className="text-[13px] font-medium">{p.session_name.replace(/^the /, "")}</p>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[12.5px] text-ink-2">
              <span className="flex items-center gap-1">
                <Clock size={12} className="text-ink-3" /> {p.day} {p.time}
              </span>
              <span className="flex items-center gap-1">
                <MapPin size={12} className="text-ink-3" /> {p.room}
              </span>
            </p>
          </div>
        ))}
      </div>
      <p className="mt-2.5 border-t border-line pt-2 text-[11.5px] text-ink-3">
        Moves {offer.moved} class{offer.moved === 1 ? "" : "es"} · cost {offer.cost.toFixed(2)}
      </p>
    </button>
  );
}

export function MessageBubble({ m, reply }: { m: MessageView; reply?: { decision: string | null; choice?: string; text?: string } }) {
  return (
    <div className="space-y-3">
      <div className="flex gap-3">
        <div className="grid size-8 shrink-0 place-items-center rounded-full bg-panel-2">
          <Mark size={16} />
        </div>
        <div className="min-w-0 flex-1 rounded-lg border border-line bg-panel p-4">
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
        <div className="flex justify-end gap-3">
          <div className="max-w-[80%] rounded-lg border border-line bg-panel-2 px-4 py-3">
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
        </div>
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
          <tr className="border-b border-line text-left text-[12px] text-ink-3">
            <th className="py-2 pr-3 font-medium">Class</th>
            <th className="py-2 pr-3 font-medium">Teacher</th>
            <th className="py-2 pr-3 font-medium">Before</th>
            <th className="py-2 pr-3" />
            <th className="py-2 font-medium">After</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.session} data-index={i} className="border-b border-line/60">
              <td className="py-2.5 pr-3">
                <p className="font-medium">{r.session_name.replace(/^the /, "")}</p>
              </td>
              <td className="py-2.5 pr-3 text-ink-2">{r.faculty_name}</td>
              <td className="py-2.5 pr-3 text-ink-3 line-through decoration-bad/50">{r.before ? `${r.before.day} ${r.before.time} · ${r.before.room}` : "—"}</td>
              <td className="py-2.5 pr-3 text-ink-3">
                <ArrowRight size={14} />
              </td>
              <td className="py-2.5 font-medium text-ok">{r.after ? `${r.after.day} ${r.after.time} · ${r.after.room}` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
