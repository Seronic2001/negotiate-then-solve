import clsx from "clsx";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  Braces,
  Cpu,
  CornerDownLeft,
  FileText,
  Gauge,
  GitCompare,
  History,
  MessagesSquare,
  Route,
  Scale,
  ShieldCheck,
  Timer,
} from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { EventTimeline, Lifecycle } from "../components/Lifecycle";
import { ConstraintCard, DiffTable, GroundedExplanation, MessageBubble } from "../components/Negotiation";
import { Avatar, Badge, Card, CardHeader, Collapse, EmptyState, Json, Meter, PageHeader, Skeleton, StatusBadge, Tabs } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";
import { ago, num, pct, secs } from "../lib/meta";
import type { CaseDetail as Detail } from "../lib/types";

type Tab = "overview" | "parse" | "policy" | "negotiation" | "change" | "trace";

export default function CaseDetail() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "overview";
  const setTab = (t: Tab) => setParams(t === "overview" ? {} : { tab: t }, { replace: true });
  const { data: c, error } = useApi(() => api.case(id), [id], 1500);

  if (error) return <EmptyState icon={AlertTriangle} title="Cannot open this request" text={error.message} />;
  if (!c)
    return (
      <div className="space-y-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-40" />
        <Skeleton className="h-72" />
      </div>
    );

  const msgs = c.outcome?.messages ?? [];
  return (
    <>
      <Link to="/requests" className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-ink-3 hover:text-ink">
        <ArrowLeft size={15} /> Requests
      </Link>
      <PageHeader
        eyebrow={
          <span className="flex items-center gap-2">
            <span className="font-mono">{c.id}</span> · {c.channel} · {ago(c.received_at)}
          </span>
        }
        title={<span className="line-clamp-2">“{c.text}”</span>}
        actions={<StatusBadge status={c.status} live={c.running} />}
      />
      <Card className="mb-6 p-5">
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <Avatar name={c.sender_name} id={c.sender} size={36} />
          <div>
            <p className="text-[14px] font-medium">{c.sender_name}</p>
            <p className="text-[12px] text-ink-3">{c.role.replace("_", " ")}</p>
          </div>
          <div className="ml-auto flex flex-wrap gap-2">
            {c.route && <Badge tone={c.route === "fast" ? "ok" : "info"}><Route size={12} /> {c.route === "fast" ? "fast path" : "System Two"}</Badge>}
            {c.type && <Badge tone="muted">{c.type.replace("_", " ")}</Badge>}
            {c.outcome && <Badge tone="warn">ladder step {c.outcome.step}</Badge>}
          </div>
        </div>
        <Lifecycle events={c.events} status={c.status} live={c.running} />
      </Card>

      <div className="mb-5">
        <Tabs
          tabs={[
            { id: "overview", label: "Overview", icon: Gauge },
            { id: "parse", label: "Parsing", icon: Braces },
            { id: "policy", label: "Policy check", icon: BookOpen },
            { id: "negotiation", label: "Conflict & negotiation", icon: MessagesSquare, count: msgs.length },
            { id: "change", label: "Change & fairness", icon: GitCompare },
            { id: "trace", label: "Trace", icon: History, count: c.events.length },
          ]}
          value={tab}
          onChange={setTab}
        />
      </div>

      <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        {tab === "overview" && <Overview c={c} />}
        {tab === "parse" && <Parsing c={c} />}
        {tab === "policy" && <Policy c={c} />}
        {tab === "negotiation" && <Negotiation c={c} />}
        {tab === "change" && <Change c={c} />}
        {tab === "trace" && (
          <Card>
            <CardHeader icon={History} title="Event trace" subtitle="Every recorded step, with the time between steps" />
            <div className="p-5">
              <EventTimeline events={c.events} />
            </div>
          </Card>
        )}
      </motion.div>
    </>
  );
}

function Overview({ c }: { c: Detail }) {
  const r = c.routing && "tau" in c.routing ? c.routing : null;
  const stages = Object.entries(c.timings);
  const maxT = Math.max(0.001, ...stages.map(([, v]) => v));
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader icon={CornerDownLeft} title="Reply sent to the requester" />
        <div className="p-5">
          {c.reply ? <p className="text-[14.5px] leading-relaxed">{c.reply}</p> : <p className="text-sm text-ink-3">Still processing…</p>}
          {Object.keys(c.notices).length > 0 && (
            <div className="mt-5">
              <p className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-3">Notified after publication (affected people only)</p>
              <div className="space-y-1.5">
                {Object.entries(c.notices).map(([who, text]) => (
                  <div key={who} className="rounded-lg bg-panel-2 px-3 py-2 text-[12.5px]">
                    <span className="font-mono text-brand">{who}</span> {text}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </Card>
      <Card>
        <CardHeader icon={Route} title="System One routing" subtitle="A calibrated classifier decides whether the fast path is safe" />
        <div className="space-y-4 p-5">
          {r ? (
            <>
              <div className="flex flex-wrap gap-2">
                <Badge tone="info">type: {r.request_type.replace("_", " ")}</Badge>
                <Badge tone="info">action: {r.action}</Badge>
                <Badge tone={r.fast_path ? "ok" : "muted"}>{r.fast_path ? "fast path taken" : "sent to System Two"}</Badge>
                <Badge tone="muted">{num(r.latency_ms, 1)} ms</Badge>
              </div>
              {[
                ["Type confidence", r.type_p],
                ["Action confidence", r.action_p],
              ].map(([label, v]) => (
                <div key={label as string}>
                  <div className="mb-1.5 flex justify-between text-[12.5px]">
                    <span className="text-ink-2">{label}</span>
                    <span className="font-mono">{pct(v as number, 1)}</span>
                  </div>
                  <div className="relative">
                    <Meter value={v as number} tone={(v as number) >= r.tau ? "ok" : "warn"} />
                    <div className="absolute -top-1 h-4 w-0.5 bg-ink" style={{ left: `${r.tau * 100}%` }} title={`τ = ${r.tau}`} />
                  </div>
                </div>
              ))}
              <p className="text-[12px] text-ink-3">The black mark is τ = {r.tau}: below it the request goes to the slower, more capable parser.</p>
            </>
          ) : (
            <p className="text-sm text-ink-3">No routing decision recorded.</p>
          )}
        </div>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader icon={Timer} title="Where the time went" />
        <div className="space-y-3 p-5">
          {stages.map(([k, v], i) => (
            <div key={k} className="grid grid-cols-[160px_minmax(0,1fr)_80px] items-center gap-3 text-[13px]">
              <span className="text-ink-2">{k.replace(/_/g, " ")}</span>
              <div className="h-6 rounded-lg bg-panel-2">
                <motion.div initial={{ width: 0 }} animate={{ width: `${(v / maxT) * 100}%` }} transition={{ delay: i * 0.1, duration: 0.8 }} className="h-full rounded-lg grad-bg" />
              </div>
              <span className="text-right font-mono text-ink-2">{secs(v)}</span>
            </div>
          ))}
          {!stages.length && <p className="text-sm text-ink-3">No timings yet.</p>}
        </div>
      </Card>
    </div>
  );
}

function Parsing({ c }: { c: Detail }) {
  const p = c.parse;
  if (!p) return <EmptyState icon={Braces} title="Not parsed yet" />;
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <Card>
        <CardHeader icon={Braces} title="What the parser returned" subtitle="Structured output only; message text never reaches a tool" />
        <div className="space-y-3 p-5">
          <div className="flex flex-wrap gap-2">
            <Badge tone="info">action: {p.action}</Badge>
            {p.refusal && <Badge tone="bad">refused: {p.refusal}</Badge>}
            {p.errors.map((e) => (
              <Badge key={e} tone="warn">
                {e}
              </Badge>
            ))}
          </div>
          <Json value={p.output} className="max-h-[480px]" />
        </div>
      </Card>
      <Card>
        <CardHeader icon={ShieldCheck} title="Typed constraints" subtitle="Tier, authority and validation are decided by code, not by the model" />
        <div className="space-y-3 p-5">
          {p.constraints.map((k, i) => (
            <ConstraintCard key={k.id} c={k} index={i} />
          ))}
          {!p.constraints.length && <p className="text-sm text-ink-3">No constraints: the request was {p.action === "answer" ? "a question" : p.action}.</p>}
        </div>
      </Card>
    </div>
  );
}

function Policy({ c }: { c: Detail }) {
  const p = c.policy;
  if (!p) return <EmptyState icon={BookOpen} title="No policy check" text="Refused, forwarded and clarification requests stop before the policy check." />;
  const tone = p.verdict === "allowed" ? "ok" : p.verdict === "forbidden" ? "bad" : "warn";
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader icon={Scale} title="Verdict" subtitle={`Policy agent (${p.mode})`} />
        <div className="space-y-4 p-5">
          <Badge tone={tone} className="text-sm">
            {p.verdict.replace("_", " ")}
          </Badge>
          <p className="text-[14px] leading-relaxed">{p.answer || p.explanation}</p>
          {p.alternative && (
            <div className="rounded-xl border border-ok/30 bg-ok/8 p-3 text-[13px]">
              <span className="font-medium text-ok">Compliant alternative: </span>
              {p.alternative}
            </div>
          )}
          {p.obligations.length > 0 && (
            <div className="rounded-xl border border-info/30 bg-info/8 p-3 text-[13px]">
              <span className="font-medium text-info">Obligation attached: </span>
              {p.obligations.join(", ")} (a make-up class within two weeks)
            </div>
          )}
          {p.uncited_escalation && <Badge tone="warn">The model denied without a valid citation, so a human decides.</Badge>}
        </div>
      </Card>
      <Card>
        <CardHeader icon={BookOpen} title="Rules retrieved" subtitle="BM25 over the handbook; citations must come from this list" />
        <div className="space-y-2 p-5">
          {p.retrieved.map((id, i) => {
            const cited = p.cited.find((x) => x.id === id);
            return (
              <motion.div
                key={id}
                initial={{ opacity: 0, x: 8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
                className={clsx("flex items-center gap-3 rounded-xl border px-3 py-2.5 text-[13px]", cited ? "border-brand/50 bg-brand/8" : "border-line")}
              >
                <span className="w-5 text-center font-mono text-[11px] text-ink-3">{i + 1}</span>
                <span className="font-mono text-[12px] text-brand">{id}</span>
                <span className="flex-1 truncate text-ink-2">{cited?.cite ?? ""}</span>
                {cited && <Badge tone="brand">cited</Badge>}
                {p.obligations.includes(id) && <Badge tone="info">obligation</Badge>}
              </motion.div>
            );
          })}
          {p.hallucinated.length > 0 && <Badge tone="bad">dropped invented citations: {p.hallucinated.join(", ")}</Badge>}
        </div>
      </Card>
    </div>
  );
}

function Negotiation({ c }: { c: Detail }) {
  const [msgIdx, setMsgIdx] = useState(0);
  const o = c.outcome;
  if (!o) return <EmptyState icon={Cpu} title="Not solved yet" />;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-4">
        {[
          ["Outcome", o.status.charAt(0).toUpperCase() + o.status.slice(1)],
          ["Ladder step", `${o.step} of 4`],
          ["Rounds", String(o.rounds)],
          ["Solver", o.solver ? `${o.solver.status.charAt(0).toUpperCase() + o.solver.status.slice(1)} · ${secs(o.solver.wall_time)}` : "—"],
        ].map(([k, v]) => (
          <Card key={k} className="p-4">
            <p className="text-[12px] text-ink-3">{k}</p>
            <p className="mt-1 text-lg font-semibold">{v}</p>
          </Card>
        ))}
      </div>
      {o.mus_log.length > 0 && (
        <Card>
          <CardHeader icon={AlertTriangle} title="The conflict, round by round" subtitle="Minimal unsatisfiable subsets from CP-SAT: every constraint listed is needed for the clash" />
          <div className="space-y-5 p-5">
            {o.mus_log.map((mus, r) => (
              <div key={r}>
                <p className="mb-2 text-xs font-medium uppercase tracking-wider text-ink-3">Round {r + 1}</p>
                <div className="grid gap-2 md:grid-cols-2">
                  {mus.map((k, i) => (
                    <ConstraintCard key={k.id} c={k} highlight index={i} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
      {o.messages.length > 0 && (
        <Card>
          <CardHeader icon={MessagesSquare} title="Negotiation thread" subtitle="Each message offers solver-verified alternatives with a grounded explanation" />
          <div className="space-y-6 p-5">
            {o.messages.map((m, i) => (
              <MessageBubble key={i} m={m} reply={o.replies[i] ? { ...o.replies[i], decision: o.replies[i].decision ?? null } : undefined} />
            ))}
          </div>
        </Card>
      )}
      {o.messages.length > 0 && (
        <Card>
          <CardHeader
            icon={FileText}
            title="Explanation grounding"
            subtitle="Hover a claim to see the facts it rests on. A checker drops claims whose days, numbers or names are not in the facts they cite."
            action={
              o.messages.length > 1 && (
                <Tabs tabs={o.messages.map((_, i) => ({ id: String(i), label: `Round ${i + 1}` }))} value={String(msgIdx)} onChange={(v) => setMsgIdx(Number(v))} />
              )
            }
          />
          <div className="p-5">
            <GroundedExplanation m={o.messages[msgIdx]} />
          </div>
        </Card>
      )}
      {o.escalation && (
        <Card>
          <CardHeader icon={AlertTriangle} title={`Escalated to ${o.escalation.to_name}`} subtitle={o.escalation.reason} />
          <pre className="whitespace-pre-wrap p-5 font-sans text-[13px] leading-relaxed text-ink-2">{o.escalation.text}</pre>
        </Card>
      )}
      {!o.mus_log.length && !o.escalation && (
        <Card className="p-6 text-sm text-ink-2">
          No conflict: the hard constraints fit, so the solver repaired the timetable directly (ladder step {o.step}
          {o.step === 2 ? ", with preference notices" : ""}).
        </Card>
      )}
    </div>
  );
}

function Change({ c }: { c: Detail }) {
  const f = c.fairness;
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <Card>
        <CardHeader
          icon={GitCompare}
          title={c.proposal ? `Proposed version ${c.proposal.version}${c.proposal.week ? ` (week ${c.proposal.week})` : ""}` : "No proposed change"}
          subtitle="Classes that move, compared with the version it builds on"
        />
        <div className="p-5">{c.proposal ? <DiffTable rows={c.proposal.diff} /> : <p className="text-sm text-ink-3">This request did not produce a timetable change.</p>}</div>
      </Card>
      <Card>
        <CardHeader icon={Scale} title="Fairness audit" subtitle="Concession Gini across teaching faculty" />
        <div className="space-y-5 p-5">
          {f.gini_after !== undefined ? (
            <>
              {(
                [
                  ["Before", f.gini_before ?? 0],
                  ["After", f.gini_after ?? 0],
                ] as const
              ).map(([k, v]) => (
                <div key={k}>
                  <div className="mb-1.5 flex justify-between text-[13px]">
                    <span className="text-ink-2">{k}</span>
                    <span className="font-mono">{num(v, 3)}</span>
                  </div>
                  <Meter value={v} tone={v > 0.5 ? "warn" : "ok"} />
                </div>
              ))}
              {f.conceded && f.conceded.length > 0 && <p className="text-[13px] text-ink-2">Conceded: {f.conceded.join(", ")}</p>}
              {f.preferences_lost && f.preferences_lost.length > 0 && <p className="text-[13px] text-ink-2">Preferences not met (notified, may appeal): {f.preferences_lost.join(", ")}</p>}
            </>
          ) : (
            <p className="text-sm text-ink-3">No audit: the request did not reach the solver.</p>
          )}
          {c.outcome?.concessions.length ? (
            <Collapse title="Ledger entries recorded">
              <Json value={c.outcome.concessions} />
            </Collapse>
          ) : null}
        </div>
      </Card>
    </div>
  );
}
