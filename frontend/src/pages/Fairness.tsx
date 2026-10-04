import { ArrowDownRight, ArrowUpRight, Info, ScrollText, TrendingDown } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, LabelList, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
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

type Entry = NonNullable<ReturnType<typeof useLedger>["data"]>["entries"][number];
const useLedger = () => useApi(() => api.ledger(), [], 5000);

/** The semester's Gini after each concession: it falls when someone new gives way, rises when the same
 * people give way again. One series, so no legend; the latest value is labelled directly. */
function GiniTrend({ entries, semester }: { entries: Entry[]; semester: string }) {
  const rows = entries
    .filter((e) => e.semester === semester)
    .map((e, i) => ({ n: i + 1, label: `${i + 1}`, name: e.name, gini: +e.gini_after.toFixed(3) }));
  if (rows.length < 2) return null;
  const last = rows.length - 1;
  return (
    <Card className="mt-6">
      <CardHeader icon={TrendingDown} title="How the Gini moved" subtitle="After each concession this semester, in order. Lower is more even." />
      <div className="h-64 px-3 pb-3 pt-5">
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 18, right: 40, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="var(--line)" vertical={false} />
            <XAxis dataKey="label" tick={{ fill: "var(--ink-3)", fontSize: 12 }} axisLine={false} tickLine={false} />
            <YAxis domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tick={{ fill: "var(--ink-3)", fontSize: 12 }} axisLine={false} tickLine={false} width={40} />
            <Tooltip
              cursor={{ stroke: "var(--ink-3)", strokeDasharray: "3 3" }}
              contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 6, fontSize: 12, color: "var(--ink)" }}
              labelFormatter={(_, p) => (p?.[0] ? `Concession ${p[0].payload.n}: ${p[0].payload.name}` : "")}
              formatter={(v) => [Number(v).toFixed(3), "Gini after"]}
            />
            <Line type="stepAfter" dataKey="gini" stroke="var(--brand)" strokeWidth={2} isAnimationActive={false}
              dot={{ r: 4, fill: "var(--brand)", stroke: "var(--panel)", strokeWidth: 2 }}
              activeDot={{ r: 6, fill: "var(--brand)", stroke: "var(--panel)", strokeWidth: 2 }}>
              <LabelList dataKey="gini" content={({ x, y, index, value }) =>
                index === last ? (
                  <text x={Number(x) + 8} y={Number(y) - 8} fill="var(--ink)" fontSize={12} fontWeight={600}>{Number(value).toFixed(2)}</text>
                ) : null} />
            </Line>
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

/** "+0.021" or "−0.125", with an arrow and a word, so the direction never rests on colour alone. */
function Moved({ entries, i }: { entries: Entry[]; i: number }) {
  const e = entries[i];
  const prev = entries.slice(0, i).reverse().find((x) => x.semester === e.semester);
  if (!prev) return <span className="w-28 text-right text-[12px] text-ink-3">first this semester</span>;
  const d = e.gini_after - prev.gini_after;
  const down = d < 0;
  const Icon = down ? ArrowDownRight : ArrowUpRight;
  return (
    <span className={`flex w-28 items-center justify-end gap-1 text-[12px] tabular-nums ${down ? "text-ok" : "text-bad"}`} title={down ? "more evenly shared" : "less evenly shared"}>
      <Icon size={13} /> {down ? "fell" : "rose"} {Math.abs(d).toFixed(3)}
    </span>
  );
}

export default function Fairness() {
  const tk = useTokens();
  const t = { ...tk, ink3: tk["ink-3"] };
  const { data } = useLedger();
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
      {data && <GiniTrend entries={data.entries} semester={data.semester} />}
      <Card className="mt-6">
        <CardHeader icon={ScrollText} title="Ledger entries" subtitle="Append-only; recorded when a concession is accepted in negotiation" />
        {data?.entries.length ? (
          <div className="divide-y divide-line">
            {data.entries.map((e, i) => (
              <div key={i} className="flex items-center gap-3 px-5 py-2.5">
                <Avatar name={e.name} id={e.stakeholder} size={30} />
                <p className="min-w-0 flex-1 text-[13.5px]">
                  <span className="font-medium">{e.name}</span> relaxed <span className="font-mono text-[12px] text-ink-3">{e.constraint_id}</span>
                  {e.case && (
                    <>
                      {" "}for{" "}
                      <Link to={`/requests/${e.case}`} className="font-mono text-[12px] text-brand hover:underline">
                        {e.case}
                      </Link>
                    </>
                  )}
                </p>
                <Badge tone="muted">{e.semester}</Badge>
                <span className="w-24 text-right text-[12.5px] tabular-nums text-ink-2">+{e.credit.toFixed(2)} credit</span>
                <span className="hidden w-20 text-right text-[12.5px] tabular-nums text-ink-2 sm:inline">Gini {e.gini_after.toFixed(3)}</span>
                <span className="hidden sm:flex"><Moved entries={data.entries} i={i} /></span>
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
