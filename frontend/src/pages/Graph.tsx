import clsx from "clsx";
import { Move, Network } from "lucide-react";
import { useState } from "react";
import { EDGE_STYLE, KnowledgeGraph, NODE_STYLE } from "../components/KnowledgeGraph";
import { Badge, Card, CardHeader, PageHeader, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";

const USES: Record<string, string> = {
  owns: "who to ask to relax a constraint",
  has_authority_over: "whether a request is valid",
  reports_to: "the escalation path",
  derived_from: "provenance for explanations",
  conflicts_with: "filled from MUS results; drives negotiation",
  references: "which resources a constraint touches",
  attended_by: "who is notified",
  member_of: "class representatives",
};

export default function Graph() {
  const { data } = useApi(() => api.graph(), [], 10000);
  const [hidden, setHidden] = useState<Set<string>>(new Set(["attended_by", "member_of", "has_authority_over"]));
  const rels = [...new Set((data?.edges ?? []).map((e) => e.rel))];
  const counts = Object.fromEntries(rels.map((r) => [r, (data?.edges ?? []).filter((e) => e.rel === r).length]));
  return (
    <>
      <PageHeader
        eyebrow="State and memory"
        title="Knowledge graph"
        subtitle="Stakeholders, constraints and resources, and how they relate. Every interpretation decision (who to ask, who may change what, where to escalate) is a query over this graph."
        actions={
          <Badge tone="muted">
            <Move size={12} /> drag to pan · scroll to zoom · hover to focus
          </Badge>
        }
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
        <Card className="overflow-hidden">
          <div className="relative h-[640px] bg-[radial-gradient(circle_at_center,var(--panel-2),var(--panel))]">
            {data ? <KnowledgeGraph data={data} hidden={hidden} /> : <Skeleton className="h-full" />}
          </div>
        </Card>
        <div className="space-y-6">
          <Card>
            <CardHeader icon={Network} title="Relations" subtitle="Toggle to declutter" />
            <div className="space-y-1 p-3">
              {rels.map((r) => {
                const st = EDGE_STYLE[r] ?? { color: "#64748b", label: r };
                const off = hidden.has(r);
                return (
                  <button
                    key={r}
                    onClick={() => setHidden((h) => {
                      const n = new Set(h);
                      if (n.has(r)) n.delete(r);
                      else n.add(r);
                      return n;
                    })}
                    className={clsx("flex w-full items-start gap-3 rounded-xl px-3 py-2 text-left transition-opacity hover:bg-panel-2", off && "opacity-40")}
                  >
                    <svg width="26" height="10" className="mt-1.5 shrink-0">
                      <line x1="0" y1="5" x2="26" y2="5" stroke={st.color} strokeWidth="2.5" strokeDasharray={st.dash} />
                    </svg>
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] font-medium">
                        {st.label} <span className="text-ink-3">({counts[r]})</span>
                      </p>
                      {USES[r] && <p className="text-[11.5px] text-ink-3">{USES[r]}</p>}
                    </div>
                  </button>
                );
              })}
            </div>
          </Card>
          <Card>
            <CardHeader title="Nodes" />
            <div className="flex flex-wrap gap-2 p-4">
              {Object.entries(NODE_STYLE)
                .filter(([k]) => k !== "rule")
                .map(([k, v]) => (
                  <span key={k} className="flex items-center gap-1.5 rounded-full bg-panel-2 px-2.5 py-1 text-[12px]">
                    <span className="size-2.5 rounded-full" style={{ background: v.color }} />
                    {v.label}
                  </span>
                ))}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
