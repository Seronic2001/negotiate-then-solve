import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import { BookOpen, Search, Sparkles } from "lucide-react";
import { useState } from "react";
import { Badge, Card, CardHeader, PageHeader, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { useApi, useDebounced } from "../lib/hooks";

const SAMPLES = ["Can I teach at 1pm?", "4 lectures back-to-back", "I missed a class for a conference", "book the auditorium", "who approves saturday classes"];

export default function Policy() {
  const { data: rules } = useApi(() => api.handbook(), []);
  const [q, setQ] = useState("Can I teach at 1pm?");
  const dq = useDebounced(q, 220);
  const { data: hits } = useApi(() => (dq.trim() ? api.search(dq) : Promise.resolve(null)), [dq]);
  const maxScore = Math.max(0.001, ...(hits?.results.map((r) => r.score ?? 0) ?? [0]));
  const [open, setOpen] = useState<string | null>(null);

  return (
    <>
      <PageHeader
        eyebrow="Knowledge (RAG)"
        title="Handbook & retrieval"
        subtitle="The policy agent sees only the rules retrieval finds, and may cite only those. Try a query to see exactly what it would be shown."
        actions={<Badge tone="warn">Synthetic stand-in: replace with the institute's handbook</Badge>}
      />
      <Card className="mb-6 overflow-hidden">
        <div className="relative p-5">
          <div className="absolute -right-10 -top-16 size-48 rounded-full bg-brand/15 blur-3xl" />
          <div className="relative flex items-center gap-3 rounded-2xl border border-line bg-panel-2 px-4 focus-within:border-brand/50 focus-within:ring-4 focus-within:ring-brand/10">
            <Search size={18} className="text-ink-3" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask like a faculty member would…" className="h-14 flex-1 bg-transparent text-[15px] outline-none" />
            <Badge tone="brand">
              <Sparkles size={12} /> BM25
            </Badge>
          </div>
          <div className="relative mt-3 flex flex-wrap gap-2">
            {SAMPLES.map((s) => (
              <button key={s} onClick={() => setQ(s)} className="rounded-full border border-line px-3 py-1 text-[12px] text-ink-2 hover:border-brand/40">
                {s}
              </button>
            ))}
          </div>
          {hits && (
            <p className="relative mt-4 flex flex-wrap items-center gap-1.5 text-[12px] text-ink-3">
              Query tokens after normalisation:
              {hits.tokens.map((t) => (
                <span key={t} className="rounded-md bg-panel-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-2 ring-1 ring-line">
                  {t}
                </span>
              ))}
              <span className="ml-1">(clock times become h13, h14…)</span>
            </p>
          )}
        </div>
        <div className="space-y-2 border-t border-line p-5">
          <AnimatePresence mode="popLayout">
            {hits?.results.map((r, i) => (
              <motion.div
                key={r.id}
                layout
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ delay: i * 0.04 }}
                className={clsx("rounded-xl border p-4", i === 0 ? "border-brand/40 bg-brand/5" : "border-line")}
              >
                <div className="flex items-center gap-3">
                  <span className="grid size-6 place-items-center rounded-md bg-panel-2 font-mono text-[11px]">{i + 1}</span>
                  <span className="font-mono text-[12px] text-brand">{r.id}</span>
                  <span className="text-[13.5px] font-medium">
                    §{r.number} {r.title}
                  </span>
                  <div className="ml-auto flex w-40 items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-panel-2">
                      <motion.div className="h-full grad-bg" initial={{ width: 0 }} animate={{ width: `${((r.score ?? 0) / maxScore) * 100}%` }} />
                    </div>
                    <span className="w-10 text-right font-mono text-[11px] text-ink-3">{r.score?.toFixed(2)}</span>
                  </div>
                </div>
                <p className="mt-2 text-[13px] leading-relaxed text-ink-2">{r.text}</p>
              </motion.div>
            ))}
          </AnimatePresence>
          {hits && !hits.results.length && <p className="py-6 text-center text-sm text-ink-3">No rule matches. The agent would see nothing and could not deny.</p>}
        </div>
      </Card>
      <Card>
        <CardHeader icon={BookOpen} title="Timetabling regulations" subtitle={`${rules?.length ?? 0} rules, each with an ID so citations can be checked`} />
        <div className="divide-y divide-line">
          {rules
            ? rules.map((r) => (
                <button key={r.id} onClick={() => setOpen(open === r.id ? null : r.id)} className="block w-full px-5 py-3.5 text-left hover:bg-panel-2/50">
                  <div className="flex items-center gap-3">
                    <span className="w-10 font-mono text-[12px] text-ink-3">§{r.number}</span>
                    <span className="flex-1 text-[14px] font-medium">{r.title}</span>
                    <span className="font-mono text-[11.5px] text-brand">{r.id}</span>
                  </div>
                  <AnimatePresence>
                    {open === r.id && (
                      <motion.p initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden pl-[52px] pt-2 text-[13px] leading-relaxed text-ink-2">
                        {r.text}
                      </motion.p>
                    )}
                  </AnimatePresence>
                </button>
              ))
            : Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="m-4 h-8" />)}
        </div>
      </Card>
    </>
  );
}
