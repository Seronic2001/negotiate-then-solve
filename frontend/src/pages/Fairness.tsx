import { Info, ScrollText } from "lucide-react";
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Avatar, Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";
import { useTokens } from "../lib/theme";

function Gauge({ value }: { value: number }) {
  const t = useTokens();
  const target = Math.max(0, Math.min(1, value));
  // Start at 0 and move to the value after the first paint, so the CSS transitions sweep.
  const [v, setV] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setV(target));
    return () => cancelAnimationFrame(id);
  }, [target]);
  const tone = target < 0.3 ? t.ok : target < 0.6 ? t.warn : t.bad;
  const arc = "M 20 100 A 80 80 0 0 1 180 100";
  const ease = "1.1s cubic-bezier(0.16, 1, 0.3, 1)";
  return (
    <svg viewBox="0 0 200 112" className="w-full max-w-[240px]">
      <path d={arc} fill="none" stroke={t.line} strokeWidth="12" strokeLinecap="round" />
      <path
        d={arc}
        fill="none"
        stroke={tone}
        strokeWidth="12"
        strokeLinecap="round"
        pathLength={1}
        style={{ strokeDasharray: `${v} 1`, opacity: v > 0 ? 1 : 0, transition: `stroke-dasharray ${ease}` }}
      />
      <line
        x1="100"
        y1="100"
        x2="100"
        y2="44"
        stroke={t.ink}
        strokeWidth="2.5"
        strokeLinecap="round"
        style={{ transform: `rotate(${-90 + v * 180}deg)`, transformOrigin: "100px 100px", transition: `transform ${ease}` }}
      />
      <circle cx="100" cy="100" r="5" fill={t.ink} />
    </svg>
  );
}

export default function Fairness() {
  const tk = useTokens();
  const t = { ...tk, ink3: tk["ink-3"] };
  const { data } = useApi(() => api.ledger(), [], 5000);
  const chart = (data?.stakeholders ?? []).map((s) => ({ name: s.name.replace("Dr. ", ""), credit: +s.credit.toFixed(2), concessions: s.concessions }));
  return (
    <>
      <PageHeader
        title="Fairness"
        subtitle="Who has given way, and how evenly it is shared. Credit halves each semester."
      />
      <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
        <Card>
          <CardHeader title="Concession Gini" subtitle={`Semester ${data?.semester ?? ""}`} />
          <div className="flex flex-col items-center p-6">
            {data ? <Gauge value={data.gini} /> : <Skeleton className="h-32 w-60" />}
            <p className="mt-2 font-serif text-4xl font-semibold tabular-nums">{data?.gini.toFixed(3) ?? "–"}</p>
            <div className="mt-2 flex w-full max-w-[260px] justify-between text-[11px] text-ink-3">
              <span>shared evenly</span>
              <span>one person carries it</span>
            </div>
            <div className="mt-6 flex gap-2 text-[12.5px] text-ink-2">
              <Info size={15} className="mt-0.5 shrink-0 text-ink-3" />
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
                <Tooltip cursor={{ fill: "var(--panel-2)" }} contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 6, fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 12 }} iconSize={8} />
                <Bar dataKey="concessions" name="Concessions" fill={t.brand} radius={[3, 3, 0, 0]} />
                <Bar dataKey="credit" name="Credit" fill={t.ink3} radius={[3, 3, 0, 0]} />
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
              <div key={i} className="flex items-center gap-3 px-5 py-2.5">
                <Avatar name={e.name} id={e.stakeholder} size={30} />
                <p className="flex-1 text-[13.5px]">
                  <span className="font-medium">{e.name}</span> relaxed <span className="font-mono text-[12px] text-ink-3">{e.constraint_id}</span>
                </p>
                <Badge tone="muted">{e.semester}</Badge>
                <span className="text-[12.5px] tabular-nums text-ink-2">+{e.credit} credit</span>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState icon={ScrollText} title="No concessions yet" text="When someone accepts an option or counter-offers, it is recorded here." />
        )}
      </Card>
    </>
  );
}
