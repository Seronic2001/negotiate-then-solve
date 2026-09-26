import { motion } from "framer-motion";
import { Activity, ArrowRight, BadgeCheck, CalendarCheck2, Cpu, Inbox, ListChecks, PenSquare, Scale, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { ActivityFeed } from "../components/Lifecycle";
import { Badge, Button, Card, CardHeader, item, LiveDot, PageHeader, Skeleton, Stagger, Stat, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { ago, ROLE_LABEL, STATUS, TONE_CLASS } from "../lib/meta";
import type { EventRow, Status } from "../lib/types";

const TONE_HEX: Record<string, string> = { brand: "#8b7dff", ok: "#34d399", warn: "#fbbf24", bad: "#fb7185", info: "#60a5fa", muted: "#6b7290" };

export function useLiveEvents(intervalMs = 1500, caseId?: string) {
  const [events, setEvents] = useState<EventRow[]>([]);
  const after = useRef(0);
  useEffect(() => {
    let stop = false;
    after.current = 0;
    setEvents([]);
    const tick = async () => {
      try {
        const rows = await api.events(after.current, caseId);
        if (rows.length && !stop) {
          after.current = rows[rows.length - 1].n;
          setEvents((e) => [...e, ...rows].slice(-400));
        }
      } catch {
        /* keep polling */
      }
    };
    void tick();
    const id = window.setInterval(tick, intervalMs);
    return () => {
      stop = true;
      window.clearInterval(id);
    };
  }, [intervalMs, caseId]);
  return events;
}

export default function Dashboard() {
  const { user, can } = useAuth();
  const { data: ov } = useApi(() => api.overview(), [], 3000);
  const { data: mine } = useApi(() => api.cases(can("see_all") ? "all" : "mine"), [], 3000);
  const events = useLiveEvents(1500);
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  const pie = ov
    ? (Object.entries(ov.counts) as [Status, number][]).map(([s, n]) => ({ name: STATUS[s]?.label ?? s, value: n, color: TONE_HEX[STATUS[s]?.tone ?? "muted"] }))
    : [];

  return (
    <>
      <PageHeader
        eyebrow={ov ? `${ov.department} · semester ${ov.semester}` : "Loading…"}
        title={
          <>
            {greet}, <span className="grad-text">{user?.name.replace(/^Dr\. /, "Dr. ")}</span>
          </>
        }
        subtitle={`Signed in as ${user ? ROLE_LABEL[user.role] : ""}. Everything below is live from the running pipeline.`}
        actions={
          <>
            {can("request") && (
              <Link to="/new">
                <Button variant="primary" icon={PenSquare}>
                  New request
                </Button>
              </Link>
            )}
            {can("approve") && (
              <Link to="/approvals">
                <Button icon={BadgeCheck}>Review approvals</Button>
              </Link>
            )}
          </>
        }
      />

      {ov?.seeding && (
        <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} className="mb-5 flex items-center gap-3 rounded-2xl border border-warn/30 bg-warn/8 px-4 py-3 text-sm">
          <LiveDot tone="warn" />
          <span>
            Replaying a demo history through the real pipeline (simulated faculty answer negotiation messages). Watch the activity feed fill up.
          </span>
        </motion.div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Requests handled" value={ov?.total ?? 0} icon={ListChecks} hint={`${ov?.sessions ?? 0} sessions · ${ov?.faculty ?? 0} faculty`} />
        <Stat
          label={can("approve") ? "Awaiting your approval" : "Your negotiation inbox"}
          value={(can("approve") ? ov?.pending_approvals : ov?.my_inbox) ?? 0}
          icon={can("approve") ? BadgeCheck : Inbox}
          tone="warn"
          delay={0.05}
          hint={can("approve") ? "nothing publishes without you" : "messages waiting for your reply"}
        />
        <Stat
          label="Negotiations agreed"
          value={ov?.negotiations.agreed ?? 0}
          icon={Sparkles}
          tone="ok"
          delay={0.1}
          hint={`${ov?.negotiations.escalated ?? 0} escalated · ${ov?.negotiations.feasible ?? 0} solved directly`}
        />
        <Stat label="Concession Gini" value={ov?.gini ?? 0} format={(v) => v.toFixed(2)} icon={Scale} tone="info" delay={0.15} hint="0 = concessions shared evenly" />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader
            icon={Activity}
            title="Live activity"
            subtitle="Every state change, negotiation message and approval, as it happens"
            action={
              <Badge tone="ok">
                <LiveDot /> streaming
              </Badge>
            }
          />
          <div className="max-h-[420px] overflow-y-auto p-3">
            <ActivityFeed events={events.slice(-40)} />
          </div>
        </Card>

        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader icon={Cpu} title="Request outcomes" subtitle={ov ? `Parser: ${ov.models.parser}` : ""} />
            <div className="flex items-center gap-4 p-5">
              <div className="h-44 w-44 shrink-0">
                {pie.length ? (
                  <ResponsiveContainer>
                    <PieChart>
                      <Pie data={pie} dataKey="value" innerRadius={52} outerRadius={78} paddingAngle={3} stroke="none" animationDuration={900}>
                        {pie.map((p) => (
                          <Cell key={p.name} fill={p.color} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 12, fontSize: 12 }} />
                    </PieChart>
                  </ResponsiveContainer>
                ) : (
                  <Skeleton className="size-44 rounded-full" />
                )}
              </div>
              <div className="flex-1 space-y-1.5">
                {pie.map((p) => (
                  <div key={p.name} className="flex items-center gap-2 text-[13px]">
                    <span className="size-2 rounded-full" style={{ background: p.color }} />
                    <span className="flex-1 text-ink-2">{p.name}</span>
                    <span className="font-medium tabular-nums">{p.value}</span>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader
              icon={CalendarCheck2}
              title={can("see_all") ? "Latest requests" : "Your requests"}
              action={
                <Link to="/requests" className="flex items-center gap-1 text-[13px] text-brand hover:underline">
                  All <ArrowRight size={14} />
                </Link>
              }
            />
            <Stagger className="divide-y divide-line">
              {(mine ?? []).slice(0, 6).map((c) => (
                <motion.div key={c.id} variants={item}>
                  <Link to={`/requests/${c.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-panel-2/60">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13.5px]">{c.text}</p>
                      <p className="mt-0.5 text-[11.5px] text-ink-3">
                        <span className="font-mono">{c.id}</span> · {c.sender_name} · {ago(c.received_at)}
                      </p>
                    </div>
                    <StatusBadge status={c.status} live={c.running} />
                  </Link>
                </motion.div>
              ))}
              {mine && !mine.length && <p className="px-5 py-8 text-center text-sm text-ink-3">No requests yet.</p>}
            </Stagger>
          </Card>
        </div>
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-3">
        {[
          { to: "/timetable", title: "Published timetable", text: `Version ${ov?.published_version ?? "–"}, with every change highlighted`, icon: CalendarCheck2, tone: "info" },
          { to: "/transparency", title: "How decisions are made", text: "Tiers, weights, the resolution ladder and the safety rules", icon: Sparkles, tone: "brand" },
          { to: "/fairness", title: "Fairness ledger", text: "Who conceded what, and how evenly it is shared", icon: Scale, tone: "ok" },
        ].map((q, i) => (
          <Link key={q.to} to={q.to}>
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 + i * 0.06 }}>
              <Card hover className="group flex items-center gap-4 p-5">
                <div className={`grid size-11 place-items-center rounded-xl ${TONE_CLASS[q.tone as "info"].bg} ${TONE_CLASS[q.tone as "info"].text}`}>
                  <q.icon size={19} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{q.title}</p>
                  <p className="truncate text-[13px] text-ink-3">{q.text}</p>
                </div>
                <ArrowRight size={16} className="text-ink-3 transition-transform group-hover:translate-x-1 group-hover:text-brand" />
              </Card>
            </motion.div>
          </Link>
        ))}
      </div>
    </>
  );
}
