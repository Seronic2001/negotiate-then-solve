import { ArrowRight, BadgeCheck, CheckCircle2, HelpCircle, Inbox, MessagesSquare, TriangleAlert, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ActivityFeed } from "../components/Lifecycle";
import { Card, CardHeader, LiveDot, PageHeader, Skeleton, Stat, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { ago, ROLE_LABEL } from "../lib/meta";
import type { EventRow, TestRun } from "../lib/types";

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

interface Todo {
  key: string;
  icon: LucideIcon;
  text: string;
  to: string;
  action: string;
}

export default function Dashboard() {
  const { user, can, sees } = useAuth();
  const oversight = can("see_all"); // coordinator, HoD and Dean see the whole department
  const { data: ov } = useApi(() => api.overview(), [], 3000);
  const { data: cases } = useApi(() => api.cases(can("see_all") ? "all" : "mine"), [], 3000);
  const { data: mine } = useApi(() => (can("see_all") ? api.cases("mine") : Promise.resolve(null)), [], 3000);
  const events = useLiveEvents(oversight ? 2000 : 60_000);
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  const own = mine ?? (can("see_all") ? [] : cases) ?? [];
  const todos: Todo[] = [];
  if (can("approve") && ov?.pending_approvals)
    todos.push({ key: "approve", icon: BadgeCheck, text: `${ov.pending_approvals} change${ov.pending_approvals > 1 ? "s" : ""} waiting for your approval`, to: "/approvals", action: "Review" });
  if (sees("inbox") && ov?.my_inbox)
    todos.push({ key: "inbox", icon: Inbox, text: `${ov.my_inbox} negotiation message${ov.my_inbox > 1 ? "s" : ""} waiting for your reply`, to: "/inbox", action: "Answer" });
  for (const c of own.filter((c) => c.status === "clarification_requested").slice(0, 3))
    todos.push({ key: c.id, icon: HelpCircle, text: `We need more detail on “${c.text}”`, to: `/requests/${c.id}`, action: "Open" });
  if (oversight && !can("approve"))
    for (const c of (cases ?? []).filter((c) => c.status === "escalated").slice(0, 3))
      todos.push({ key: c.id, icon: TriangleAlert, text: `Escalated for a decision: “${c.text}”`, to: `/requests/${c.id}?tab=negotiation`, action: "Decide" });
  for (const c of own.filter((c) => c.status === "negotiating").slice(0, 3))
    todos.push({ key: c.id, icon: MessagesSquare, text: `“${c.text}” is being negotiated with a colleague`, to: `/requests/${c.id}`, action: "Follow" });

  return (
    <>
      <PageHeader
        title={`${greet}, ${user?.name ?? ""}`}
        subtitle={ov ? `${user ? ROLE_LABEL[user.role] : ""} · ${ov.department}, semester ${ov.semester}` : " "}
      />

      {ov?.seeding && (
        <p className="mb-5 flex items-center gap-2 text-[13px] text-ink-2">
          <LiveDot tone="warn" /> {ov.test_run ? "Replaying held-out test requests through the real pipeline; the lists below fill in as it runs." : "Loading a demo history through the real pipeline; the lists below fill in as it runs."}
        </p>
      )}

      {oversight && ov?.test_run && <TestRunCard run={ov.test_run} />}

      <Card className={oversight ? "mb-6" : "mb-6 max-w-3xl"}>
        <CardHeader title="Needs you" />
        {!ov ? (
          <Skeleton className="m-5 h-10" />
        ) : todos.length ? (
          <ul className="divide-y divide-line">
            {todos.map((t) => (
              <li key={t.key}>
                <Link to={t.to} className="group flex items-center gap-3 px-5 py-3 hover:bg-panel-2/60">
                  <t.icon size={16} className="shrink-0 text-brand" />
                  <span className="min-w-0 flex-1 truncate text-[14px]">{t.text}</span>
                  <span className="flex shrink-0 items-center gap-1 text-[13px] font-medium text-brand">
                    {t.action} <ArrowRight size={14} className="transition-transform group-hover:translate-x-0.5" />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="flex items-center gap-2.5 px-5 py-4 text-[14px] text-ink-2">
            <CheckCircle2 size={16} className="text-ok" /> Nothing needs you right now.
          </p>
        )}
      </Card>

      {oversight && (
      <Card className="mb-6 grid grid-cols-2 gap-y-5 p-5 lg:grid-cols-4 lg:divide-x lg:divide-line lg:[&>*]:px-5 lg:[&>*:first-child]:pl-0">
        <Stat label="Requests handled" value={ov?.total ?? 0} hint={`${ov?.sessions ?? 0} classes · ${ov?.faculty ?? 0} teachers`} />
        <Stat label="Agreed by negotiation" value={ov?.negotiations.agreed ?? 0} hint={`${ov?.negotiations.feasible ?? 0} fitted without asking anyone`} />
        <Stat label="Escalated" value={ov?.negotiations.escalated ?? 0} hint="sent to someone with authority" />
        <Stat label="Concession Gini" value={ov?.gini ?? 0} format={(v) => v.toFixed(2)} hint="0 means concessions are shared evenly" />
      </Card>
      )}

      <div className={oversight ? "grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]" : "max-w-3xl"}>
        <Card>
          <CardHeader
            title={oversight ? "Recent requests" : "Your requests"}
            action={
              <Link to="/requests" className="text-[13px] text-brand hover:underline">
                See all
              </Link>
            }
          />
          <ul className="divide-y divide-line">
            {(cases ?? []).slice(0, 7).map((c) => (
              <li key={c.id}>
                <Link to={`/requests/${c.id}`} className="flex items-center gap-3 px-5 py-2.5 hover:bg-panel-2/60">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13.5px]">{c.text}</p>
                    <p className="mt-0.5 text-[12px] text-ink-3">
                      {oversight ? `${c.sender_name} · ` : ""}
                      {ago(c.received_at)}
                    </p>
                  </div>
                  <StatusBadge status={c.status} live={c.running} />
                </Link>
              </li>
            ))}
            {cases && !cases.length && (
              <li className="px-5 py-8 text-center text-[13px] text-ink-3">
                No requests yet.{" "}
                {sees("new") && (
                  <Link to="/new" className="text-brand hover:underline">
                    Write one
                  </Link>
                )}
              </li>
            )}
            {!cases && <Skeleton className="m-5 h-40" />}
          </ul>
        </Card>

        {oversight && (
        <Card>
          <CardHeader
            title="Activity"
            action={
              sees("health") && (
                <Link to="/observability" className="text-[13px] text-brand hover:underline">
                  System health
                </Link>
              )
            }
          />
          <div className="max-h-[400px] overflow-y-auto p-2">
            <ActivityFeed events={events.slice(-25)} compact />
          </div>
        </Card>
        )}
      </div>
    </>
  );
}

function TestRunCard({ run }: { run: TestRun }) {
  const done = run.rows.length;
  const matches = run.rows.filter((r) => r.match).length;
  return (
    <Card className="mb-6">
      <CardHeader
        title="Held-out test requests"
        subtitle={`${done} of ${run.n} replayed · ${matches} of ${done} match the gold action${done ? ` (${Math.round((100 * matches) / done)}%)` : ""}`}
      />
      <ul className="max-h-80 divide-y divide-line overflow-y-auto">
        {run.rows.map((r) => (
          <li key={r.case}>
            <Link to={`/requests/${r.case}`} className="flex items-center gap-3 px-5 py-2.5 hover:bg-panel-2/60">
              <span className={`w-12 shrink-0 text-[12px] font-semibold ${r.match ? "text-ok" : "text-bad"}`}>{r.match ? "OK" : "MISS"}</span>
              <span className="w-16 shrink-0 font-mono text-[12px] text-ink-3">{r.corpus_id}</span>
              <span className="min-w-0 flex-1 truncate text-[13px]">{r.text}</span>
              <span className="shrink-0 text-[12px] text-ink-2">
                gold <b>{r.expected}</b> · got <b>{r.got ?? "–"}</b>
              </span>
              {r.error && <span className="shrink-0 text-[12px] text-bad" title={r.error}>error</span>}
              <StatusBadge status={r.status} />
            </Link>
          </li>
        ))}
        {done < run.n && (
          <li className="flex items-center gap-2 px-5 py-2.5 text-[13px] text-ink-2">
            <LiveDot tone="warn" pulse /> Running request {done + 1} of {run.n}…
          </li>
        )}
      </ul>
    </Card>
  );
}
