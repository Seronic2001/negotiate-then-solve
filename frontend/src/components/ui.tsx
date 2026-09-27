import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight, Loader2, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { colorFor, initials, STATUS, TIER, TONE_CLASS, type Tone } from "../lib/meta";
import type { Status } from "../lib/types";

export function Card({ className, children, hover }: { className?: string; children: ReactNode; hover?: boolean }) {
  return (
    <div className={clsx("min-w-0 rounded-lg border border-line bg-panel", hover && "transition-colors hover:border-ink-3/60", className)}>
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  icon: Icon,
  action,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: LucideIcon;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-3.5">
      <div className="min-w-0">
        <h3 className="flex items-center gap-2 text-[14px] font-semibold">
          {Icon && <Icon size={15} className="shrink-0 text-ink-3" />}
          {title}
        </h3>
        {subtitle && <p className="mt-0.5 text-[12.5px] text-ink-3">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";

export function Button({
  variant = "secondary",
  size = "md",
  icon: Icon,
  loading,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; icon?: LucideIcon; loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={clsx(
        "inline-flex select-none items-center justify-center gap-2 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-[13px]" : "h-9 px-3.5 text-[13.5px]",
        variant === "primary" && "bg-brand text-panel hover:bg-brand/90",
        variant === "secondary" && "border border-line bg-panel text-ink hover:bg-panel-2",
        variant === "ghost" && "text-ink-2 hover:bg-panel-2 hover:text-ink",
        variant === "danger" && "border border-bad/30 text-bad hover:bg-bad/8",
        variant === "success" && "bg-ok text-panel hover:bg-ok/90",
        className,
      )}
    >
      {loading ? <Loader2 size={15} className="animate-spin" /> : Icon ? <Icon size={15} /> : null}
      {children}
    </button>
  );
}

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
    <Badge tone={t.tone}>
      <span className="font-mono">T{tier}</span>
      <span className="opacity-80">{t.name}</span>
    </Badge>
  );
}

/** A small status dot; ``pulse`` marks something still running. */
export function LiveDot({ tone = "ok", pulse = true }: { tone?: Tone; pulse?: boolean }) {
  return <span className={clsx("inline-block size-1.5 shrink-0 rounded-full", TONE_CLASS[tone].dot, pulse && "animate-pulse")} />;
}

export function Stat({ label, value, format, hint }: { label: string; value: number; format?: (v: number) => string; hint?: ReactNode; icon?: LucideIcon; tone?: Tone; delay?: number }) {
  return (
    <div className="min-w-0">
      <p className="text-[12.5px] text-ink-3">{label}</p>
      <p className="mt-1 font-serif text-[28px] leading-none font-semibold tabular-nums">{format ? format(value) : value}</p>
      {hint && <p className="mt-1.5 text-[12px] text-ink-3">{hint}</p>}
    </div>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string; icon?: LucideIcon; count?: number }[];
  value: T;
  onChange: (t: T) => void;
}) {
  return (
    <div className="inline-flex max-w-full gap-0.5 overflow-x-auto rounded-md border border-line bg-panel-2 p-0.5">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={clsx(
            "flex shrink-0 items-center gap-1.5 rounded px-2.5 py-1 text-[13px] font-medium transition-colors",
            value === t.id ? "bg-panel text-ink shadow-[0_0_0_1px_var(--line)]" : "text-ink-3 hover:text-ink",
          )}
        >
          {t.icon && <t.icon size={14} />}
          {t.label}
          {t.count !== undefined && t.count > 0 && <span className="text-[11.5px] tabular-nums text-ink-3">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Avatar({ name, id, size = 32 }: { name: string; id?: string; size?: number }) {
  const c = colorFor(id ?? name);
  return (
    <div
      className="grid shrink-0 place-items-center rounded-full font-semibold"
      style={{ width: size, height: size, fontSize: size * 0.38, color: c, background: `color-mix(in oklab, ${c} 16%, var(--panel))` }}
    >
      {initials(name)}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton rounded-md", className)} />;
}

export function EmptyState({ icon: Icon, title, text, action }: { icon: LucideIcon; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <Icon size={22} className="text-ink-3" />
      <p className="mt-3 font-medium">{title}</p>
      {text && <p className="mt-1 max-w-sm text-[13px] text-ink-3">{text}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Meter({ value, max = 1, tone = "brand", className }: { value: number; max?: number; tone?: Tone; className?: string }) {
  const p = Math.max(0, Math.min(1, max ? value / max : 0));
  return (
    <div className={clsx("h-1.5 overflow-hidden rounded-full bg-panel-2", className)}>
      <div className={clsx("h-full rounded-full transition-[width] duration-500", TONE_CLASS[tone].dot)} style={{ width: `${p * 100}%` }} />
    </div>
  );
}

export function Json({ value, className }: { value: unknown; className?: string }) {
  const text = JSON.stringify(value, null, 2) ?? "null";
  const html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?)/g, (m, str, colon, lit, n) => {
      if (str) return colon ? `<span class="text-brand">${str}</span>${colon}` : `<span class="text-ok">${str}</span>`;
      if (lit) return `<span class="text-warn">${lit}</span>`;
      if (n) return `<span class="text-info">${n}</span>`;
      return m;
    });
  return (
    <pre
      className={clsx("overflow-auto rounded-md border border-line bg-panel-2 p-4 font-mono text-[12px] leading-relaxed text-ink-2", className)}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export function Collapse({ title, children, defaultOpen = false }: { title: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-line bg-panel">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-4 py-3 text-left text-[13.5px] font-medium">
        <ChevronRight size={15} className={clsx("text-ink-3 transition-transform", open && "rotate-90")} />
        {title}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} transition={{ duration: 0.18 }} className="overflow-hidden">
            <div className="border-t border-line px-4 py-4">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
      <div className="min-w-0">
        <h1 className="font-serif text-[28px] leading-tight font-semibold">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-[13.5px] text-ink-3">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** A small uppercase label above a group of fields. */
export function Label({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={clsx("mb-2 text-[11.5px] font-medium uppercase tracking-wide text-ink-3", className)}>{children}</p>;
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-line bg-panel-2 px-1 py-px font-mono text-[10.5px] text-ink-3">{children}</kbd>;
}

export function Toast({ message, tone = "ok", onDone }: { message: string | null; tone?: Tone; onDone: () => void }) {
  // Callers pass an inline onDone, which changes on every render; keying the timer on it
  // restarted the countdown each time a polling page re-rendered, so the toast never left.
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    if (!message) return;
    const id = window.setTimeout(() => done.current(), 3200);
    return () => window.clearTimeout(id);
  }, [message]);
  return (
    <AnimatePresence>
      {message && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2">
          <div className="flex items-center gap-2.5 rounded-md bg-ink px-4 py-2.5 text-[13.5px] text-bg shadow-lg">
            <span className={clsx("size-1.5 rounded-full", TONE_CLASS[tone].dot)} />
            {message}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** The mark: a timetable grid with one cell settled. */
export function Mark({ size = 22, className }: { size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={clsx("shrink-0 text-brand", className)} aria-hidden>
      <rect x="2.5" y="3.5" width="19" height="17" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.7" />
      <path d="M2.5 8.5h19M8.8 8.5v12M15.2 8.5v12" stroke="currentColor" strokeWidth="1.4" />
      <rect x="9.6" y="9.3" width="4.8" height="5.1" rx="0.8" fill="currentColor" />
    </svg>
  );
}
