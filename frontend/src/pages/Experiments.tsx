import clsx from "clsx";
import { Cpu, FlaskConical, MessagesSquare, ShieldCheck } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";
import { useTokens } from "../lib/theme";
import { ago, num, pct } from "../lib/meta";
import type { Experiment, ModelRow, NegotiationSummary, PairedTest } from "../lib/types";

const CONFIG_LABEL: Record<string, string> = {
  ours: "Ours",
  "ours-llm": "Ours (LLM)",
  A1: "A1 · flat, no ledger",
  A2: "A2 · free explanations",
  A3: "A3 · rule replies",
  "A1-offline": "A1 · flat (offline)",
  B1: "B1 · LLM only",
  B2: "B2 · solver only",
  B3: "B3 · unverified",
  B4: "B4 · filtered",
  oracle: "Oracle",
};

const METRICS: { key: keyof NegotiationSummary; label: string; fmt: (v: number | null) => string; better: "high" | "low" }[] = [
  { key: "correct_outcome", label: "Correct outcome", fmt: (v) => pct(v), better: "high" },
  { key: "validity_of_timetables", label: "Valid timetables", fmt: (v) => pct(v), better: "high" },
  { key: "agreement_rate", label: "Resolution rate", fmt: (v) => pct(v), better: "high" },
  { key: "rounds_mean", label: "Rounds (resolved)", fmt: (v) => num(v), better: "low" },
  { key: "objective_gap_abs_mean", label: "Distance to oracle", fmt: (v) => num(v), better: "low" },
  { key: "escalation_precision", label: "Escalation P", fmt: (v) => num(v), better: "high" },
  { key: "escalation_recall", label: "Escalation R", fmt: (v) => num(v), better: "high" },
  { key: "concession_gini", label: "Burden Gini", fmt: (v) => num(v), better: "low" },
  { key: "burden_max", label: "Max burden", fmt: (v) => num(v), better: "low" },
  { key: "first_proposal_acceptance", label: "1st-offer accept", fmt: (v) => pct(v), better: "high" },
  { key: "explanation_faithfulness", label: "Faithfulness", fmt: (v) => pct(v), better: "high" },
  { key: "private_leaks", label: "Leaks", fmt: (v) => String(v ?? 0), better: "low" },
];

export default function Experiments() {
  const { data } = useApi(() => api.experiments(), []);
  return (
    <>
      <PageHeader
        title="Experiments"
        subtitle="Results from the evaluation scripts in runs/."
      />
      {!data ? (
        <Skeleton className="h-96" />
      ) : !data.length ? (
        <Card>
          <EmptyState icon={FlaskConical} title="No results yet" text="Run uv run python -m evaluation.negotiation --offline to produce the first report." />
        </Card>
      ) : (
        <div className="space-y-6">
          {data.map((e) => (
            <ExperimentCard key={e.id} e={e} />
          ))}
        </div>
      )}
    </>
  );
}

function ExperimentCard({ e }: { e: Experiment }) {
  const t = useTokens();
  if (e.kind === "negotiation") {
    const configs = Object.entries(e.configs);
    const chart = configs.map(([k, s]) => ({
      name: CONFIG_LABEL[k] ?? k,
      "Correct outcome": +(100 * (s.correct_outcome ?? 0)).toFixed(1),
      "Resolution rate": +(100 * (s.agreement_rate ?? 0)).toFixed(1),
    }));
    return (
      <Card>
        <CardHeader icon={MessagesSquare} title={e.title} subtitle={`${e.subtitle ? `${e.subtitle} · ` : ""}updated ${ago(e.at)}`} />
        <div className="h-64 p-5">
          <ResponsiveContainer>
            <BarChart data={chart}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: "var(--ink-3)", fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis unit="%" tick={{ fill: "var(--ink-3)", fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ fill: "var(--panel-2)" }} contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 6, fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="Correct outcome" fill={t.brand} radius={[3, 3, 0, 0]} />
              <Bar dataKey="Resolution rate" fill={t["ink-3"]} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="overflow-x-auto border-t border-line">
          <table className="w-full min-w-[980px] text-[12.5px]">
            <thead>
              <tr className="border-b border-line text-left text-[11.5px] text-ink-3">
                <th className="px-5 py-2.5 font-medium">Config</th>
                <th className="px-2 py-2.5 text-right font-medium">Runs</th>
                {METRICS.map((m) => (
                  <th key={m.key} className="px-2 py-2.5 text-right font-medium">
                    {m.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {configs.map(([k, s]) => (
                <tr key={k} className={clsx("border-b border-line/60", k.startsWith("ours") && "bg-panel-2")}>
                  <td className="px-5 py-2.5 font-medium">{CONFIG_LABEL[k] ?? k}</td>
                  <td className="px-2 py-2.5 text-right font-mono text-ink-3">{s.n}</td>
                  {METRICS.map((m) => {
                    const vals = configs.map(([, x]) => x[m.key] as number | null).filter((x): x is number => typeof x === "number");
                    const v = s[m.key] as number | null;
                    const best = typeof v === "number" && vals.length > 1 && v === (m.better === "high" ? Math.max(...vals) : Math.min(...vals));
                    return (
                      <td key={m.key} className={clsx("px-2 py-2.5 text-right font-mono", best ? "font-semibold text-ok" : "text-ink-2")}>
                        {m.fmt(v)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {e.paired && Object.keys(e.paired).length > 0 && <Paired paired={e.paired} />}
      </Card>
    );
  }
  if (e.kind === "models") return <Models e={e} />;
  const s = e.summary as Record<string, number | Record<string, string>>;
  const cats = s.by_category as Record<string, string>;
  return (
    <Card>
      <CardHeader icon={ShieldCheck} title={e.title} subtitle={`${s.n} cases · ${ago(e.at)}`} />
      <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Pass rate" v={pct(s.pass_rate as number, 0)} />
        <Metric label="Unapproved publishes" v={String(s.unapproved_publishes)} />
        <Metric label="Authority violations" v={String(s.authority_violations)} />
        <Metric label="Injection successes" v={String(s.injection_successes)} />
      </div>
      <div className="flex flex-wrap gap-2 border-t border-line p-5">
        {Object.entries(cats ?? {}).map(([k, v]) => (
          <Badge key={k} tone={v.split("/")[0] === v.split("/")[1] ? "ok" : "warn"}>
            {k.replace(/_/g, " ")}: {v}
          </Badge>
        ))}
      </div>
    </Card>
  );
}

function Metric({ label, v }: { label: string; v: string }) {
  return (
    <div>
      <p className="text-[12px] text-ink-3">{label}</p>
      <p className="mt-1 font-serif text-2xl font-semibold tabular-nums">{v}</p>
    </div>
  );
}

function Paired({ paired }: { paired: Record<string, PairedTest> }) {
  return (
    <div className="overflow-x-auto border-t border-line px-5 py-4">
      <p className="mb-2 text-[12.5px] font-medium text-ink-2">Paired tests (same scenario and seed)</p>
      <table className="w-full min-w-[560px] text-[12.5px]">
        <thead>
          <tr className="text-left text-[11.5px] text-ink-3">
            <th className="py-1.5 font-medium">Comparison</th>
            <th className="py-1.5 text-right font-medium">Pairs</th>
            <th className="py-1.5 text-right font-medium">Only first right</th>
            <th className="py-1.5 text-right font-medium">Only second right</th>
            <th className="py-1.5 text-right font-medium">McNemar p</th>
            <th className="py-1.5 text-right font-medium">Objective Wilcoxon p</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(paired).map(([k, v]) => {
            const [a, b] = k.split(" vs ");
            const p = v.correct_outcome_mcnemar.p;
            return (
              <tr key={k} className="border-t border-line/60">
                <td className="py-1.5">
                  {CONFIG_LABEL[a] ?? a} vs {CONFIG_LABEL[b] ?? b}
                </td>
                <td className="py-1.5 text-right font-mono">{v.pairs}</td>
                <td className="py-1.5 text-right font-mono">{v.correct_outcome_mcnemar.only_first}</td>
                <td className="py-1.5 text-right font-mono">{v.correct_outcome_mcnemar.only_second}</td>
                <td className={clsx("py-1.5 text-right font-mono", p < 0.05 && "font-semibold text-ok")}>{fmtP(p)}</td>
                <td className={clsx("py-1.5 text-right font-mono", v.objective_wilcoxon.n > 0 && v.objective_wilcoxon.p < 0.05 && "font-semibold text-ok")}>
                  {v.objective_wilcoxon.n ? fmtP(v.objective_wilcoxon.p) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const fmtP = (p: number) => (p < 0.001 ? p.toExponential(1) : p.toFixed(3));

type Col = { key: keyof ModelRow; label: string; group: string; fmt: (v: number | string) => string; better?: "high" | "low" };

const MODEL_COLS: Col[] = [
  { key: "reply_tool", label: "Action", group: "Replies", fmt: (v) => pct(v as number, 0), better: "high" },
  { key: "reply_args", label: "Details", group: "Replies", fmt: (v) => pct(v as number, 1), better: "high" },
  { key: "to_coordinator", label: "To coord.", group: "Replies", fmt: (v) => String(v), better: "low" },
  { key: "parse_action", label: "Action", group: "Parsing", fmt: (v) => pct(v as number, 1), better: "high" },
  { key: "compile_exact", label: "Compile exact", group: "Parsing", fmt: (v) => pct(v as number, 1), better: "high" },
  { key: "injections", label: "Injections", group: "Parsing", fmt: (v) => String(v) },
  { key: "latency_p50", label: "p50 s", group: "Parsing", fmt: (v) => num(v as number, 2), better: "low" },
  { key: "policy_allow_deny", label: "Allow/deny", group: "Policy", fmt: (v) => pct(v as number, 0), better: "high" },
  { key: "deny_recall", label: "Deny recall", group: "Policy", fmt: (v) => pct(v as number, 0), better: "high" },
  { key: "makeup_recall", label: "Make-up", group: "Policy", fmt: (v) => pct(v as number, 0), better: "high" },
  { key: "swap_pairs", label: "Right pair", group: "Swaps", fmt: (v) => pct(v as number, 0), better: "high" },
  { key: "swap_wrong", label: "Wrong commits", group: "Swaps", fmt: (v) => String(v), better: "low" },
];

const groupStart = (i: number) => i === 0 || MODEL_COLS[i - 1].group !== MODEL_COLS[i].group;

function Models({ e }: { e: Extract<Experiment, { kind: "models" }> }) {
  const groups: { group: string; span: number }[] = [];
  for (const c of MODEL_COLS) {
    const last = groups[groups.length - 1];
    if (last && last.group === c.group) last.span++;
    else groups.push({ group: c.group, span: 1 });
  }
  return (
    <Card>
      <CardHeader icon={Cpu} title={e.title} subtitle={`${e.subtitle ?? ""} · updated ${ago(e.at)}`} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1100px] text-[12.5px]">
          <thead>
            <tr className="text-[11.5px] text-ink-3">
              <th />
              {groups.map((g) => (
                <th key={g.group} colSpan={g.span} className="border-l border-line px-2 pt-2.5 text-center font-medium">
                  {g.group}
                </th>
              ))}
            </tr>
            <tr className="border-b border-line text-left text-[11.5px] text-ink-3">
              <th className="px-5 py-2 font-medium">Model</th>
              {MODEL_COLS.map((c, i) => (
                <th key={c.key} className={clsx("px-2 py-2 text-right font-medium", groupStart(i) && "border-l border-line")}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {e.rows.map((r) => (
              <tr key={r.model} className={clsx("border-b border-line/60", r.model.includes("4B fine-tuned · Q8") && "bg-panel-2")}>
                <td className="px-5 py-2.5 font-medium">{r.model}</td>
                {MODEL_COLS.map((c, i) => {
                  const v = r[c.key];
                  const vals = e.rows.map((x) => x[c.key]).filter((x): x is number => typeof x === "number");
                  const best = typeof v === "number" && !!c.better && vals.length > 1 && v === (c.better === "high" ? Math.max(...vals) : Math.min(...vals));
                  return (
                    <td
                      key={c.key}
                      className={clsx("px-2 py-2.5 text-right font-mono", groupStart(i) && "border-l border-line", best ? "font-semibold text-ok" : v === null ? "text-ink-3" : "text-ink-2")}
                    >
                      {v === null ? "—" : c.fmt(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
