import { AnimatePresence, motion } from "framer-motion";
import { BadgeCheck, Bell, ExternalLink, MessagesSquare, Scale, Users, XCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { DiffTable } from "../components/Negotiation";
import { Avatar, Badge, Button, Card, EmptyState, PageHeader, Skeleton, Toast } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";
import { ago, num } from "../lib/meta";
import type { CaseDetail } from "../lib/types";

export default function Approvals() {
  const { data, refresh, loading } = useApi(() => api.approvals(), [], 3000);
  const [toast, setToast] = useState<string | null>(null);
  const [gone, setGone] = useState<Set<string>>(new Set());

  const list = (data ?? []).filter((c) => !gone.has(c.id));
  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle="Nothing is published until you approve it."
      />
      {loading && !data ? (
        <Skeleton className="h-80" />
      ) : list.length ? (
        <div className="space-y-6">
          <AnimatePresence>
            {list.map((c) => (
              <motion.div key={c.id} exit={{ opacity: 0, transition: { duration: 0.2 } }}>
                <ApprovalCard
                  c={c}
                  onDone={async (msg) => {
                    setGone((g) => new Set(g).add(c.id));
                    setToast(msg);
                    await refresh();
                  }}
                />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      ) : (
        <Card>
          <EmptyState icon={BadgeCheck} title="All caught up" text="Changes that need your approval will appear here." />
        </Card>
      )}
      <Toast message={toast} onDone={() => setToast(null)} />
    </>
  );
}

function ApprovalCard({ c, onDone }: { c: CaseDetail; onDone: (msg: string) => Promise<void> }) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const diff = c.proposal?.diff ?? [];
  const people = new Set(diff.flatMap((d) => [d.faculty_name ?? "", ...d.groups.map((g) => `Section ${g.replace("G-", "").replace(/^0/, "")}`)]).filter(Boolean));
  const o = c.outcome;

  const approve = async () => {
    setBusy("approve");
    try {
      const r = await api.approve(c.id);
      await onDone(`Published version ${r.version}. Notified ${Object.keys(r.notified).length} affected people.`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card>
      <div className="flex flex-wrap items-start gap-4 border-b border-line p-5">
        <Avatar name={c.sender_name} id={c.sender} size={40} />
        <div className="min-w-0 flex-1">
          <p className="text-[15px] font-medium leading-snug">“{c.text}”</p>
          <p className="mt-1 text-[12.5px] text-ink-3">
            <Link to={`/requests/${c.id}`} className="font-mono text-brand hover:underline">
              {c.id}
            </Link>{" "}
            · {c.sender_name} · {ago(c.received_at)} · proposes version {c.proposal?.version}
            {c.proposal?.week ? ` for week ${c.proposal.week}` : " (semester timetable)"}
          </p>
        </div>
        <div className="flex gap-2">
          <Button icon={XCircle} onClick={() => setRejecting(!rejecting)} disabled={!!busy}>
            Reject
          </Button>
          <Button variant="primary" icon={BadgeCheck} loading={busy === "approve"} onClick={approve}>
            Approve and publish
          </Button>
        </div>
      </div>
      <AnimatePresence>
        {rejecting && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden border-b border-line bg-panel-2">
            <div className="flex flex-wrap items-center gap-3 p-4">
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Why? The case goes back to negotiation with your note."
                className="h-10 flex-1 rounded-md border border-line bg-panel px-3 text-sm outline-none focus:border-bad/50"
              />
              <Button
                variant="danger"
                loading={busy === "reject"}
                onClick={async () => {
                  setBusy("reject");
                  try {
                    await api.reject(c.id, reason);
                    await onDone("Sent back to negotiation.");
                  } finally {
                    setBusy(null);
                  }
                }}
              >
                Confirm rejection
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <div className="grid gap-0 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="border-b border-line p-5 lg:border-b-0 lg:border-r">
          <p className="mb-3 text-xs font-medium text-ink-3">Changes ({diff.length})</p>
          <DiffTable rows={diff} />
        </div>
        <div className="space-y-5 p-5">
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-ink-3">
              <Users size={13} /> Affected, will be notified
            </p>
            <div className="flex flex-wrap gap-1.5">
              {[...people].map((p) => (
                <Badge key={p} tone="info">
                  <Bell size={11} /> {p}
                </Badge>
              ))}
              {!people.size && <span className="text-sm text-ink-3">Nobody else.</span>}
            </div>
          </div>
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-ink-3">
              <MessagesSquare size={13} /> How it was resolved
            </p>
            <p className="text-[13.5px] text-ink-2">
              {o?.status === "agreed"
                ? `Negotiated in ${o.rounds} round${o.rounds > 1 ? "s" : ""}: ${o.concessions.map((x) => x.name).join(", ") || "—"} conceded.`
                : o?.step === 2
                  ? "Solved directly; some preferences could not be kept and their owners were told."
                  : "Solved directly; no one had to concede."}
            </p>
            {c.policy && (
              <p className="mt-1.5 text-[13px] text-ink-3">
                Policy: {c.policy.verdict}
                {c.policy.obligations.length ? ` · obligation ${c.policy.obligations.join(", ")}` : ""}
              </p>
            )}
          </div>
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-ink-3">
              <Scale size={13} /> Fairness
            </p>
            <p className="text-[13.5px]">
              Gini {num(c.fairness.gini_before ?? 0, 3)} → <span className="font-semibold">{num(c.fairness.gini_after ?? 0, 3)}</span>
            </p>
          </div>
          <Link to={`/requests/${c.id}`} className="inline-flex items-center gap-1.5 text-[13px] text-brand hover:underline">
            Full audit trail <ExternalLink size={13} />
          </Link>
        </div>
      </div>
    </Card>
  );
}
