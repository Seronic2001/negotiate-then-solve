import clsx from "clsx";
import { type ReactNode } from "react";
import { STATUS, TIER, TONE_CLASS, type Tone } from "../../lib/meta";
import type { Status } from "../../lib/types";

export function Badge({ tone = "muted", children, className, dot }: { tone?: Tone; children: ReactNode; className?: string; dot?: boolean }) {
  const t = TONE_CLASS[tone];
  return (
    <span className={clsx("inline-flex items-center gap-1.5 whitespace-nowrap rounded px-1.5 py-0.5 text-[11.5px] font-medium", t.text, t.bg, className)}>
      {dot && <span className={clsx("size-1.5 rounded-full", t.dot)} />}
      {children}
    </span>
  );
}

export function StatusBadge({ status, live }: { status: Status; live?: boolean }) {
  const s = STATUS[status] ?? STATUS.received;
  const Icon = s.icon;
  return (
    <Badge tone={s.tone}>
      {live ? <LiveDot tone={s.tone} /> : <Icon size={12} />}
      {s.label}
    </Badge>
  );
}

export function TierBadge({ tier }: { tier: number }) {
  const t = TIER[tier] ?? TIER[5];
  return (
    <span title={`Tier ${tier}. ${t.who}.`} className="cursor-help">
      <Badge tone={t.tone}>{t.name}</Badge>
    </span>
  );
}

/** A small status dot; ``pulse`` marks something still running. */
export function LiveDot({ tone = "ok", pulse = true }: { tone?: Tone; pulse?: boolean }) {
  return <span className={clsx("inline-block size-1.5 shrink-0 rounded-full", TONE_CLASS[tone].dot, pulse && "animate-pulse")} />;
}
