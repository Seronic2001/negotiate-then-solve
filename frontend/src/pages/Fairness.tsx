import { motion } from "framer-motion";
import { Info, Scale, ScrollText } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Avatar, Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";

function Gauge({ value }: { value: number }) {
  const angle = -90 + value * 180;
  return (
    <svg viewBox="0 0 200 120" className="w-full max-w-[260px]">
      <defs>
        <linearGradient id="g-gini" x1="0" x2="1">
          <stop offset="0%" stopColor="#34d399" />
          <stop offset="55%" stopColor="#fbbf24" />
          <stop offset="100%" stopColor="#fb7185" />
        </linearGradient>
      </defs>
      <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="var(--line)" strokeWidth="14" strokeLinecap="round" />
      <motion.path
        d="M 20 100 A 80 80 0 0 1 180 100"
        fill="none"
        stroke="url(#g-gini)"
        strokeWidth="14"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: Math.max(0.001, value) }}
        transition={{ duration: 1.2, ease: [0.16, 1, 0.3, 1] }}
      />
      <motion.line x1="100" y1="100" x2="100" y2="36" stroke="var(--ink)" strokeWidth="3" strokeLinecap="round" initial={{ rotate: -90 }} animate={{ rotate: angle }} style={{ originX: "100px", originY: "100px" }} transition={{ duration: 1.2, ease: [0.16, 1, 0.3, 1] }} />
      <circle cx="100" cy="100" r="6" fill="var(--ink)" />
    </svg>
  );
}

export default function Fairness() {
  const { data } = useApi(() => api.ledger(), [], 5000);
  const chart = (data?.stakeholders ?? []).map((s) => ({ name: s.name.replace("Dr. ", ""), credit: +s.credit.toFixed(2), concessions: s.concessions }));
  return (
    <>
      <PageHeader
        eyebrow="Concession ledger"
        title="Fairness"
        subtitle="Every accepted concession earns credit. Credit makes you less likely to be asked next time, and it halves each semester so history matters without dominating."
      />
      <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
        <Card>
          <CardHeader icon={Scale} title="Concession Gini" subtitle={`Semester ${data?.semester ?? ""}`} />
          <div className="flex flex-col items-center p-6">
            {data ? <Gauge value={data.gini} /> : <Skeleton className="h-32 w-60" />}
            <p className="mt-2 text-4xl font-semibold tabular-nums">{data?.gini.toFixed(3) ?? "–"}</p>
            <div className="mt-2 flex w-full max-w-[260px] justify-between text-[11px] text-ink-3">
              <span>shared evenly</span>
              <span>one person carries it</span>
            </div>
            <div className="mt-6 flex gap-2 rounded-xl bg-panel-2 p-3 text-[12.5px] text-ink-2">
              <Info size={15} className="mt-0.5 shrink-0 text-brand" />
              Among equally costly options the negotiator asks whoever has conceded least recently, which pushes this towards 0.
            </div>
          </div>
        </Card>
        <Card>
          <CardHeader title="Credit and concessions per teacher" subtitle={`Credit decays ×${data?.decay ?? 0.5} per semester`} />
          <div className="h-80 p-5">
            <ResponsiveContainer>
              <BarChart data={chart} barGap={4}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
                <XAxis dataKey="name" tick={{ fill: "var(--ink-3)", fontSize: 12 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "var(--ink-3)", fontSize: 12 }} axisLine={false} tickLine={false} allowDecimals />
                <Tooltip cursor={{ fill: "var(--panel-2)" }} contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} />
                <Bar dataKey="concessions" fill="#8b7dff" radius={[6, 6, 0, 0]} animationDuration={900} />
                <Bar dataKey="credit" fill="#38d0f5" radius={[6, 6, 0, 0]} animationDuration={1100} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>
      <Card className="mt-6">
        <CardHeader icon={ScrollText} title="Ledger entries" subtitle="Append-only; recorded when a concession is accepted in negotiation" />
        {data?.entries.length ? (
          <div className="divide-y divide-line">
            {data.entries.map((e, i) => (
              <motion.div key={i} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.04 }} className="flex items-center gap-3 px-5 py-3">
                <Avatar name={e.name} id={e.stakeholder} size={30} />
                <p className="flex-1 text-[13.5px]">
                  <span className="font-medium">{e.name}</span> relaxed <span className="font-mono text-[12px] text-brand">{e.constraint_id}</span>
                </p>
                <Badge tone="muted">{e.semester}</Badge>
                <Badge tone={e.credit >= 1 ? "brand" : "info"}>+{e.credit} credit</Badge>
              </motion.div>
            ))}
          </div>
        ) : (
          <EmptyState icon={ScrollText} title="No concessions yet" text="When someone accepts an option or counter-offers, it is recorded here." />
        )}
      </Card>
    </>
  );
}
