import clsx from "clsx";
import { motion } from "framer-motion";
import { Brain, Layers, Lock, Ratio, ShieldCheck, Workflow } from "lucide-react";
import { Badge, Card, CardHeader, Meter, PageHeader, Skeleton, TierBadge } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";
import { pct, ROLE_LABEL } from "../lib/meta";
import type { Role } from "../lib/types";

const TERMS: [string, string, string][] = [
  ["auth", "Authority", "role of the owner"],
  ["impact", "Impact", "students affected"],
  ["just", "Justification", "none / stated / verified"],
  ["lead", "Lead time", "how early it was asked"],
  ["credit", "Fairness credit", "past concessions"],
  ["disrupt", "Disruption", "classes it forces to move (subtracted)"],
];

export default function Transparency() {
  const { data } = useApi(() => api.transparency(), []);
  if (!data) return <Skeleton className="h-[600px]" />;
  const w = data.weights;
  return (
    <>
      <PageHeader
        eyebrow="Published rules of the system"
        title="How decisions are made"
        subtitle="Priorities are lexicographic across tiers and weighted within a tier: no number of preferences can outweigh a rule. The weights below are configured and published by the academic office."
      />
      <Card className="mb-6">
        <CardHeader icon={Layers} title="Priority tiers" subtitle="Lower tiers always win; only Tiers 3–4 are relaxed in negotiation" />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-[13.5px]">
            <thead>
              <tr className="border-b border-line text-left text-[11.5px] uppercase tracking-wider text-ink-3">
                <th className="px-5 py-3 font-medium">Tier</th>
                <th className="px-3 py-3 font-medium">Who may relax it</th>
                <th className="px-3 py-3 font-medium">Examples</th>
                <th className="px-5 py-3 font-medium">In negotiation</th>
              </tr>
            </thead>
            <tbody>
              {data.tiers.map((t, i) => (
                <motion.tr key={t.tier} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.06 }} className="border-b border-line/60">
                  <td className="px-5 py-3">
                    <TierBadge tier={t.tier} />
                  </td>
                  <td className="px-3 py-3 text-ink-2">{t.who}</td>
                  <td className="px-3 py-3 text-ink-3">{t.examples}</td>
                  <td className="px-5 py-3">
                    {t.relaxable_in_negotiation ? <Badge tone="warn">may be negotiated</Badge> : t.tier === 5 ? <Badge tone="muted">objective (soft)</Badge> : <Badge tone="bad">escalate only</Badge>}
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader icon={Ratio} title="Score within a tier" subtitle="π_k for each constraint k" />
          <div className="p-5">
            <div className="rounded-xl bg-panel-2 p-4 text-center font-mono text-[13px] leading-loose">
              π<sub>k</sub> = {TERMS.map(([k, , ], i) => (
                <span key={k}>
                  {i === TERMS.length - 1 ? " − " : i ? " + " : ""}
                  <span className="text-brand">{w[k]}</span>·{k}
                </span>
              ))}
            </div>
            <div className="mt-5 space-y-3">
              {TERMS.map(([k, label, hint]) => (
                <div key={k} className="grid grid-cols-[130px_minmax(0,1fr)_40px] items-center gap-3 text-[13px]">
                  <div>
                    <p className="font-medium">{label}</p>
                    <p className="text-[11px] text-ink-3">{hint}</p>
                  </div>
                  <Meter value={w[k]} max={1} tone={k === "disrupt" ? "bad" : "brand"} />
                  <span className="text-right font-mono">{w[k]}</span>
                </div>
              ))}
            </div>
            <div className="mt-5 rounded-xl border border-line p-4 text-center font-mono text-[12.5px]">
              cost(M) = Σ<sub>k∈M</sub> π<sub>k</sub> + <span className="text-brand">{w.moved}</span>·moved + <span className="text-brand">{w.fairness}</span>·ΔGini
            </div>
            <p className="mt-2 text-center text-[12px] text-ink-3">The owner of the cheapest correction set is asked first; ties go to whoever has conceded least.</p>
          </div>
        </Card>
        <Card>
          <CardHeader icon={Workflow} title="The resolution ladder" subtitle="The cheapest resolution is always tried first" />
          <div className="relative p-5">
            <div className="absolute bottom-8 left-[37px] top-8 w-px bg-gradient-to-b from-brand to-brand-2" />
            <div className="space-y-4">
              {data.ladder.map((s, i) => (
                <motion.div key={s.step} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.1 + i * 0.12 }} className="relative flex gap-4">
                  <div className="z-10 grid size-9 shrink-0 place-items-center rounded-full grad-bg text-sm font-bold text-white shadow-lg shadow-brand/30">{s.step}</div>
                  <div className="rounded-xl border border-line bg-panel-2/50 p-3.5">
                    <p className="font-medium">{s.name}</p>
                    <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{s.text}</p>
                  </div>
                </motion.div>
              ))}
            </div>
            <div className="mt-5 flex flex-wrap gap-2 text-[12px]">
              {Object.entries(data.negotiation).map(([k, v]) => (
                <Badge key={k} tone="muted">
                  {k.replace(/_/g, " ")}: {v}
                </Badge>
              ))}
            </div>
          </div>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader title="Role authority" subtitle="auth term" />
          <div className="space-y-2.5 p-5">
            {Object.entries(data.role_authority)
              .sort((a, b) => b[1] - a[1])
              .map(([r, v]) => (
                <div key={r} className="grid grid-cols-[minmax(0,1fr)_90px_36px] items-center gap-3 text-[13px]">
                  <span className="text-ink-2">{ROLE_LABEL[r as Role] ?? r}</span>
                  <Meter value={v} />
                  <span className="text-right font-mono text-[12px]">{v}</span>
                </div>
              ))}
          </div>
        </Card>
        <Card>
          <CardHeader icon={Brain} title="Models in use" subtitle="System One routes; the parser and policy agent only return data" />
          <div className="space-y-3 p-5 text-[13px]">
            <Row k="Parser (System Two)" v={data.models.parser} />
            <Row k="Policy agent" v={data.models.policy} />
            <Row k="System One" v={`TF-IDF + logistic regression · ${data.system_one.trained_on ?? "–"} examples`} />
            <Row k="Routing threshold τ" v={String(data.system_one.tau ?? "–")} />
            <Row k="System One val. accuracy" v={pct(data.system_one.val_action_accuracy, 1)} />
          </div>
        </Card>
        <Card>
          <CardHeader icon={ShieldCheck} title="Safety guarantees" subtitle="Enforced by code, not by the model" />
          <ul className="space-y-2.5 p-5">
            {data.safety.map((s, i) => (
              <motion.li key={s} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.08 }} className="flex gap-2.5 text-[13px] leading-relaxed">
                <Lock size={14} className="mt-0.5 shrink-0 text-ok" />
                {s}
              </motion.li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className={clsx("flex items-start justify-between gap-3 border-b border-line/60 pb-2 last:border-0")}>
      <span className="text-ink-3">{k}</span>
      <span className="text-right font-medium">{v}</span>
    </div>
  );
}
