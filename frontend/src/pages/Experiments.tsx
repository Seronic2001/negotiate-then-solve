import clsx from "clsx";
import { FlaskConical, MessagesSquare, ScanText, Scale, ShieldCheck } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";
import { useTokens } from "../lib/theme";
import { ago, num, pct } from "../lib/meta";
import type { Experiment, NegotiationSummary } from "../lib/types";

const CONFIG_LABEL: Record<string, string> = {
  ours: "Ours",
  "ours-llm": "Ours (LLM)",
  A1: "A1 · LLM options",
  A2: "A2 · flat, no ledger",
  A3: "A3 · free explanations",
  B1: "B1 · LLM only",
  B2: "B2 · imposed",
  B3: "B3 · free negotiation",
  B4: "B4 · oracle",
};

const METRICS: { key: keyof NegotiationSummary; label: string; fmt: (v: number | null) => string; better: "high" | "low" }[] = [
  { key: "correct_outcome", label: "Correct outcome", fmt: (v) => pct(v), better: "high" },
  { key: "validity_of_timetables", label: "Valid timetables", fmt: (v) => pct(v), better: "high" },
  { key: "agreement_rate", label: "Agreement rate", fmt: (v) => pct(v), better: "high" },
  { key: "rounds_mean", label: "Rounds", fmt: (v) => num(v), better: "low" },
  { key: "within_10pct_of_oracle", label: "Within 10% of oracle", fmt: (v) => pct(v), better: "high" },
  { key: "escalation_precision", label: "Escalation P", fmt: (v) => num(v), better: "high" },
  { key: "escalation_recall", label: "Escalation R", fmt: (v) => num(v), better: "high" },
  { key: "concession_gini", label: "Gini", fmt: (v) => num(v), better: "low" },
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
      "Agreement rate": +(100 * (s.agreement_rate ?? 0)).toFixed(1),
    }));
    return (
      <Card>
        <CardHeader icon={MessagesSquare} title={e.title} subtitle={`updated ${ago(e.at)} · ${configs[0]?.[1].n ?? 0} scenarios`} />
        <div className="h-64 p-5">
          <ResponsiveContainer>
            <BarChart data={chart}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: "var(--ink-3)", fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis unit="%" tick={{ fill: "var(--ink-3)", fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ fill: "var(--panel-2)" }} contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 6, fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="Correct outcome" fill={t.brand} radius={[3, 3, 0, 0]} />
              <Bar dataKey="Agreement rate" fill={t["ink-3"]} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="overflow-x-auto border-t border-line">
          <table className="w-full min-w-[980px] text-[12.5px]">
            <thead>
              <tr className="border-b border-line text-left text-[11.5px] text-ink-3">
                <th className="px-5 py-2.5 font-medium">Config</th>
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
      </Card>
    );
  }
  if (e.kind === "parsing") {
    const two = e.system_two as Record<string, number | string | Record<string, number>>;
    const one = e.system_one ?? {};
    return (
      <Card>
        <CardHeader icon={ScanText} title={e.title} subtitle={`${String(two.model ?? "")} · ${ago(e.at)}`} />
        <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="System Two action accuracy" v={pct(two.action_accuracy as number, 1)} />
          <Metric label="Constraints matching the label" v={pct(two.compile_semantic_match as number, 1)} />
          <Metric label="Injections handled" v={`${two.injections_handled}/${two.injections_total}`} />
          <Metric label="System One fast-path share" v={pct(one.fast_path_share, 1)} />
        </div>
      </Card>
    );
  }
  if (e.kind === "policy") {
    const s = e.summary as Record<string, number | string>;
    return (
      <Card>
        <CardHeader icon={Scale} title={e.title} subtitle={`${String(s.model ?? "")} · ${ago(e.at)}`} />
        <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="Allow/deny accuracy" v={pct(s.allow_deny_accuracy as number, 1)} />
          <Metric label="Denials citing the right rule" v={pct(s.deny_citation_correct as number, 1)} />
          <Metric label="Make-up obligations found" v={pct(s.makeup_obligation_recall as number, 1)} />
          <Metric label="Invented citations" v={String(s.hallucinated_citations)} />
        </div>
      </Card>
    );
  }
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
