import clsx from "clsx";
import { animate, AnimatePresence, motion, useMotionValue, useTransform } from "framer-motion";
import { ChevronRight, Loader2, type LucideIcon } from "lucide-react";
import { useEffect, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { colorFor, initials, STATUS, TIER, TONE_CLASS, type Tone } from "../lib/meta";
import type { Status } from "../lib/types";

export function Card({ className, children, hover }: { className?: string; children: ReactNode; hover?: boolean }) {
  return (
    <motion.div
      layout="position"
      whileHover={hover ? { y: -2 } : undefined}
      transition={{ type: "spring", stiffness: 400, damping: 30 }}
      className={clsx(
        "min-w-0 rounded-2xl border border-line bg-panel shadow-[0_1px_0_0_rgba(255,255,255,0.03)_inset,0_8px_24px_-12px_rgba(0,0,0,0.25)]",
        hover && "transition-colors hover:border-brand/40",
        className,
      )}
    >
      {children}
    </motion.div>
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
    <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
      <div className="flex min-w-0 items-start gap-3">
        {Icon && (
          <div className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-brand/12 text-brand">
            <Icon size={16} />
          </div>
        )}
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold tracking-tight">{title}</h3>
          {subtitle && <p className="mt-0.5 text-[13px] text-ink-3">{subtitle}</p>}
        </div>
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
        "inline-flex select-none items-center justify-center gap-2 rounded-xl font-medium transition-all active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-[13px]" : "h-10 px-4 text-sm",
        variant === "primary" && "grad-bg text-white shadow-lg shadow-brand/25 hover:brightness-110",
        variant === "secondary" && "border border-line bg-panel-2 text-ink hover:border-brand/40 hover:bg-panel",
        variant === "ghost" && "text-ink-2 hover:bg-panel-2 hover:text-ink",
        variant === "danger" && "bg-bad/12 text-bad ring-1 ring-bad/25 hover:bg-bad/20",
        variant === "success" && "bg-ok text-white shadow-lg shadow-ok/25 hover:brightness-110",
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
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-[11.5px] font-medium ring-1 ring-inset",
        t.text,
        t.bg,
        t.ring,
        className,
      )}
    >
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

export function LiveDot({ tone = "ok" }: { tone?: Tone }) {
  const t = TONE_CLASS[tone];
  return (
    <span className="relative inline-flex size-2">
      <span className={clsx("absolute inset-0 rounded-full animate-pulse-ring", t.dot)} />
      <span className={clsx("relative size-2 rounded-full", t.dot)} />
    </span>
  );
}

export function AnimatedNumber({ value, format = (v) => Math.round(v).toString() }: { value: number; format?: (v: number) => string }) {
  const mv = useMotionValue(0);
  const text = useTransform(mv, (v) => format(v));
  const [display, setDisplay] = useState(format(0));
  useEffect(() => {
    const c = animate(mv, value, { duration: 0.9, ease: [0.16, 1, 0.3, 1] });
    const unsub = text.on("change", setDisplay);
    return () => {
      c.stop();
      unsub();
    };
  }, [value, mv, text]);
  return <span className="tabular-nums">{display}</span>;
}

export function Stat({
  label,
  value,
  format,
  hint,
  icon: Icon,
  tone = "brand",
  delay = 0,
}: {
  label: string;
  value: number;
  format?: (v: number) => string;
  hint?: ReactNode;
  icon: LucideIcon;
  tone?: Tone;
  delay?: number;
}) {
  const t = TONE_CLASS[tone];
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay, duration: 0.45 }}>
      <Card className="relative overflow-hidden p-5">
        <div className={clsx("absolute -right-6 -top-6 size-24 rounded-full blur-2xl", t.bg)} />
        <div className="relative flex items-start justify-between">
          <div>
            <p className="text-[13px] text-ink-3">{label}</p>
            <p className="mt-2 text-3xl font-semibold tracking-tight">
              <AnimatedNumber value={value} format={format} />
            </p>
            {hint && <p className="mt-1 text-xs text-ink-3">{hint}</p>}
          </div>
          <div className={clsx("grid size-10 place-items-center rounded-xl ring-1 ring-inset", t.bg, t.text, t.ring)}>
            <Icon size={18} />
          </div>
        </div>
      </Card>
    </motion.div>
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
    <div className="flex gap-1 overflow-x-auto rounded-xl border border-line bg-panel-2 p-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={clsx(
            "relative flex shrink-0 items-center gap-2 rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors",
            value === t.id ? "text-ink" : "text-ink-3 hover:text-ink-2",
          )}
        >
          {value === t.id && (
            <motion.span layoutId="tab-pill" className="absolute inset-0 rounded-lg bg-panel shadow-sm ring-1 ring-line" transition={{ type: "spring", stiffness: 500, damping: 38 }} />
          )}
          <span className="relative flex items-center gap-2">
            {t.icon && <t.icon size={14} />}
            {t.label}
            {t.count !== undefined && t.count > 0 && (
              <span className="rounded-full bg-brand/15 px-1.5 text-[11px] text-brand">{t.count}</span>
            )}
          </span>
        </button>
      ))}
    </div>
  );
}

export function Avatar({ name, id, size = 32 }: { name: string; id?: string; size?: number }) {
  const c = colorFor(id ?? name);
  return (
    <div
      className="grid shrink-0 place-items-center rounded-full font-semibold text-white ring-2 ring-panel"
      style={{ width: size, height: size, fontSize: size * 0.36, background: `linear-gradient(135deg, ${c}, ${c}99)` }}
    >
      {initials(name)}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton rounded-lg", className)} />;
}

export function EmptyState({ icon: Icon, title, text, action }: { icon: LucideIcon; title: string; text?: string; action?: ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} className="flex flex-col items-center px-6 py-14 text-center">
      <div className="grid size-14 place-items-center rounded-2xl bg-panel-2 text-ink-3 ring-1 ring-line">
        <Icon size={24} />
      </div>
      <p className="mt-4 font-medium">{title}</p>
      {text && <p className="mt-1 max-w-sm text-sm text-ink-3">{text}</p>}
      {action && <div className="mt-5">{action}</div>}
    </motion.div>
  );
}

export function Meter({ value, max = 1, tone = "brand", className }: { value: number; max?: number; tone?: Tone; className?: string }) {
  const p = Math.max(0, Math.min(1, max ? value / max : 0));
  return (
    <div className={clsx("h-2 overflow-hidden rounded-full bg-panel-2 ring-1 ring-inset ring-line", className)}>
      <motion.div
        className={clsx("h-full rounded-full", tone === "brand" ? "grad-bg" : TONE_CLASS[tone].dot)}
        initial={{ width: 0 }}
        animate={{ width: `${p * 100}%` }}
        transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
      />
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
      className={clsx("overflow-auto rounded-xl border border-line bg-panel-2 p-4 font-mono text-[12px] leading-relaxed text-ink-2", className)}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export function Collapse({ title, children, defaultOpen = false }: { title: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-line">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium">
        <motion.span animate={{ rotate: open ? 90 : 0 }}>
          <ChevronRight size={15} className="text-ink-3" />
        </motion.span>
        {title}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="px-4 pb-4">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <div className="mb-2 text-xs font-medium uppercase tracking-[0.14em] text-brand">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight sm:text-[28px]">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-2xl text-sm text-ink-3">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Stagger({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div
      className={className}
      initial="hidden"
      animate="show"
      variants={{ hidden: {}, show: { transition: { staggerChildren: 0.045 } } }}
    >
      {children}
    </motion.div>
  );
}

export const item = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.16, 1, 0.3, 1] as const } },
};

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded-md border border-line bg-panel-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-3">{children}</kbd>;
}

export function Toast({ message, tone = "ok", onDone }: { message: string | null; tone?: Tone; onDone: () => void }) {
  useEffect(() => {
    if (!message) return;
    const id = window.setTimeout(onDone, 3200);
    return () => window.clearTimeout(id);
  }, [message, onDone]);
  return (
    <AnimatePresence>
      {message && (
        <motion.div
          initial={{ opacity: 0, y: 24, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 12 }}
          className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2"
        >
          <div className={clsx("glass flex items-center gap-3 rounded-2xl border border-line px-4 py-3 text-sm shadow-2xl", TONE_CLASS[tone].text)}>
            <LiveDot tone={tone} />
            <span className="text-ink">{message}</span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
