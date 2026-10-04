import { Activity, Brain, Cpu, Database, Gauge, Radio, Route, ShieldCheck, Timer, TriangleAlert } from "lucide-react";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ActivityFeed } from "../components/Lifecycle";
import { Badge, Card, CardHeader, LiveDot, Meter, PageHeader, Skeleton, Stat } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";
import { useTokens } from "../lib/theme";
import { EVENT_LABEL, pct, secs } from "../lib/meta";
import { useLiveEvents } from "./Dashboard";

export default function Observability() {
  const { data: o } = useApi(() => api.observability(), [], 2500);
  const events = useLiveEvents(1200);
  const t = useTokens();
  if (!o)
    return (
      <>
        <PageHeader title="System health" subtitle="Model quota, latency per stage, routing and the safety counters." />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="mt-6 h-80" />
      </>
    );
  const kinds = Object.entries(o.events_by_kind)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
    .map(([k, v]) => ({ name: EVENT_LABEL[k] ?? k, v }));
  const stages = Object.entries(o.stages);
  const maxStage = Math.max(0.001, ...stages.map(([, s]) => s.p95 ?? 0));
  const up = o.uptime_s;

  return (
    <>
      <PageHeader
        title="System health"
        subtitle="Model quota, latency per stage, routing and the safety counters."
        actions={
          <Badge tone="ok">
            <LiveDot /> up {up > 3600 ? `${(up / 3600).toFixed(1)} h` : `${Math.round(up / 60)} min`} · {o.threads_running} running
          </Badge>
        }
      />
      <Card className="grid grid-cols-2 gap-5 p-5 xl:grid-cols-4">
        <Stat label="Events recorded" value={Object.values(o.events_by_kind).reduce((a, b) => a + b, 0)} icon={Activity} />
        <Stat label="Explanation faithfulness" value={(o.explanations.faithfulness ?? 1) * 100} format={(v) => `${v.toFixed(0)}%`} icon={Brain} tone="ok" delay={0.05} hint={`${o.explanations.messages} messages · ${o.explanations.rejected_claims} claims rejected`} />
        <Stat label="Unapproved publishes" value={o.safety.unapproved_publishes} icon={ShieldCheck} tone={o.safety.unapproved_publishes ? "bad" : "ok"} delay={0.1} hint={`${o.safety.refused} refused · ${o.safety.denied} denied`} />
        <Stat label="Private-reason leaks" value={o.safety.leaks} icon={TriangleAlert} tone={o.safety.leaks ? "bad" : "ok"} delay={0.15} hint="measured on every message" />
      </Card>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader icon={Database} title="LLM usage" subtitle={`Parser: ${o.models.parser} · Policy: ${o.models.policy}`} />
          <div className="space-y-4 p-5">
            {o.llm.map((m) => (
              <div key={m.model}>
                <div className="mb-1.5 flex items-center justify-between text-[13px]">
                  <span className="font-mono text-[12.5px]">{m.model}</span>
                  <span className="text-ink-3">
                    {m.model.startsWith("local:") ? (
                      <>local model · no quota · {m.cached_responses} cached</>
                    ) : (
                      <><span className="font-medium text-ink">{m.used_today}</span> / {m.rpd ?? "?"} today · {m.cached_responses} cached</>
                    )}
                  </span>
                </div>
                {!m.model.startsWith("local:") && (
                  <Meter value={m.used_today} max={m.rpd ?? 1} tone={m.rpd && m.used_today / m.rpd > 0.85 ? "bad" : m.rpd && m.used_today / m.rpd > 0.6 ? "warn" : "brand"} />
                )}
              </div>
            ))}
            {!o.llm.length && <p className="text-sm text-ink-3">No LLM calls: running on the offline parser and policy rules.</p>}
            <p className="text-[12px] text-ink-3">Responses are cached by prompt hash, so reruns cost nothing; a daily-quota stop resumes the next day.</p>
          </div>
        </Card>

        <Card>
          <CardHeader icon={Timer} title="Latency by stage" subtitle="p50 (solid) and p95 (faint), across requests handled since start" />
          <div className="space-y-4 p-5">
            {stages.map(([k, s]) => (
              <div key={k} className="grid grid-cols-[150px_minmax(0,1fr)_130px] items-center gap-3 text-[13px]">
                <span className="text-ink-2">{k.replace(/_/g, " ")}</span>
                <div className="relative h-5 rounded bg-panel-2">
                  <div className="absolute inset-y-0 left-0 rounded bg-brand/20" style={{ width: `${((s.p95 ?? 0) / maxStage) * 100}%` }} />
                  <div className="absolute inset-y-0 left-0 rounded bg-brand" style={{ width: `${((s.p50 ?? 0) / maxStage) * 100}%` }} />
                </div>
                <span className="text-right font-mono text-[12px] text-ink-2">
                  {secs(s.p50)} / {secs(s.p95)}
                </span>
              </div>
            ))}
            <div className="flex flex-wrap gap-2 border-t border-line pt-4">
              <Badge tone="info">
                <Cpu size={12} /> CP-SAT p50 {secs(o.solver.p50)} · p95 {secs(o.solver.p95)} ({o.solver.n} solves)
              </Badge>
              <Badge tone="ok">
                <Route size={12} /> System One p50 {o.routing.system_one_latency_ms_p50?.toFixed(1) ?? "–"} ms
              </Badge>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader icon={Gauge} title="Routing" subtitle={`System One sends confident requests down the fast path (τ = ${o.routing.tau})`} />
          <div className="flex items-center gap-6 p-5">
            <div className="relative grid size-36 place-items-center">
              <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90">
                <circle cx="18" cy="18" r="15.9" fill="none" stroke="var(--line)" strokeWidth="3.2" />
                <circle
                  cx="18"
                  cy="18"
                  r="15.9"
                  fill="none"
                  stroke={t.brand}
                  strokeWidth="3.2"
                  pathLength={1}
                  strokeDasharray={`${o.routing.fast_path_share ?? 0} 1`}
                />
              </svg>
              <div className="text-center">
                <p className="font-serif text-2xl font-semibold">{pct(o.routing.fast_path_share)}</p>
                <p className="text-[11px] text-ink-3">fast path</p>
              </div>
            </div>
            <div className="flex-1 space-y-2 text-[13px]">
              {Object.entries(o.routing.counts).map(([k, v]) => (
                <div key={k} className="flex justify-between border-b border-line/60 pb-2">
                  <span className="text-ink-2">{k === "fast" ? "Fast path (compiler)" : k === "system_two" ? "System Two parser" : k || "not routed"}</span>
                  <span className="font-medium">{v}</span>
                </div>
              ))}
              <p className="pt-1 text-[12px] text-ink-3">Proposal target H3a: at least 60% on the fast path.</p>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader icon={Activity} title="Events by kind" />
          <div className="p-4" style={{ height: 40 + kinds.length * 26 }}>
            <ResponsiveContainer>
              <BarChart data={kinds} layout="vertical" margin={{ left: 40 }}>
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="name" interval={0} tick={{ fill: "var(--ink-3)", fontSize: 11 }} width={170} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: "var(--panel-2)" }} contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 6, fontSize: 12 }} />
                <Bar dataKey="v" radius={[0, 3, 3, 0]}>
                  {kinds.map((k, i) => (
                    <Cell key={k.name} fill={i === 0 ? t.brand : t.info} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader
          icon={Radio}
          title="Event stream"
          subtitle="Tail of the audit log"
          action={
            <Badge tone="ok">
              <LiveDot /> live
            </Badge>
          }
        />
        <div className="max-h-96 overflow-y-auto p-3">
          <ActivityFeed events={events.slice(-60)} />
        </div>
      </Card>
      {o.errors.length > 0 && (
        <Card className="mt-6 border-bad/40">
          <CardHeader icon={TriangleAlert} title="Recent errors" />
          <div className="space-y-2 p-5">
            {o.errors.map((e) => (
              <p key={e.n} className="font-mono text-[12px] text-bad">
                {e.case} · {String(e.error)}
              </p>
            ))}
          </div>
        </Card>
      )}
    </>
  );
}
