import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, CornerDownLeft, Mail, MessageCircle, MonitorSmartphone, Send, Sparkles, Wand2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { EventTimeline, Lifecycle } from "../components/Lifecycle";
import { Badge, Button, Card, CardHeader, Kbd, LiveDot, PageHeader, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { STATUS } from "../lib/meta";

export default function NewRequest() {
  const { user } = useAuth();
  const [text, setText] = useState("");
  const [caseId, setCaseId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const { data: inst } = useApi(() => api.instance(), []);
  const { data: detail } = useApi(() => (caseId ? api.case(caseId) : Promise.resolve(null)), [caseId], caseId ? 900 : undefined);

  const examples = useMemo(() => {
    if (!user || !inst) return [];
    const mine = inst.sessions.filter((s) => s.faculty === user.id);
    const practical = mine.find((s) => s.kind === "practical");
    if (user.role === "student") return ["Machine Learning and Algorithms clash on Tuesday at 10 am for 12 of us. Can this be looked at?", "Please cancel Dr. Khan's Friday lecture, we have a quiz."];
    if (user.role === "lab_incharge") return ["Lab 1 is closed for maintenance in weeks 11-12.", "Lab 2 will be unavailable in week 6 while the wiring is replaced."];
    if (user.role === "coordinator") return ["Who has to approve moving a class outside regular hours?"];
    return [
      "I'm at a conference in week 10, Wednesday and Thursday, so I can't take my classes then.",
      "I'd prefer no classes before 11 am on Friday, if possible.",
      practical ? `My ${practical.title} practical needs the routers; it has to be on Wednesday afternoon.` : "Please keep my Friday afternoons free.",
      "Could you schedule my lecture at 1 pm on Thursday? It's the only time that works.",
      "I'll be away for a couple of days next month.",
      "Is it allowed to teach more than three hours in a row?",
    ];
  }, [user, inst]);

  const send = async () => {
    if (!text.trim()) return;
    setSending(true);
    setError(null);
    try {
      const { id } = await api.submit(text.trim());
      setCaseId(id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  };

  const done = detail && (STATUS[detail.status]?.terminal || detail.status === "awaiting_approval" || detail.status === "negotiating");

  return (
    <>
      <PageHeader
        eyebrow="Portal"
        title="New request"
        subtitle="Write the way you would write an email. The system turns it into typed constraints, checks the rules, solves, and negotiates if something clashes. You can follow every step."
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <Card className="overflow-hidden">
          <div className="flex items-center gap-2 border-b border-line px-5 py-3 text-[12.5px] text-ink-3">
            <Badge tone="brand">
              <MonitorSmartphone size={12} /> Portal
            </Badge>
            <span className="flex items-center gap-1">
              <Mail size={12} /> Email and <MessageCircle size={12} /> messaging land in the same pipeline
            </span>
          </div>
          <div className="p-5">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void send();
              }}
              rows={7}
              placeholder="e.g. I'm at a conference in week 7, Tuesday to Thursday."
              className="w-full resize-none rounded-xl border border-line bg-panel-2 p-4 text-[14.5px] leading-relaxed outline-none transition-colors placeholder:text-ink-3 focus:border-brand/60 focus:ring-4 focus:ring-brand/10"
            />
            <div className="mt-3 flex items-center justify-between">
              <p className="flex items-center gap-1.5 text-xs text-ink-3">
                <Kbd>Ctrl</Kbd> <Kbd>Enter</Kbd> to send
              </p>
              <Button variant="primary" icon={Send} loading={sending} onClick={send} disabled={!text.trim()}>
                Send request
              </Button>
            </div>
            {error && <p className="mt-3 rounded-xl bg-bad/10 px-3 py-2 text-sm text-bad">{error}</p>}
          </div>
          <div className="border-t border-line px-5 py-4">
            <p className="mb-2.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-ink-3">
              <Wand2 size={13} /> Try one
            </p>
            <div className="flex flex-wrap gap-2">
              {examples.map((ex) => (
                <motion.button
                  key={ex}
                  whileHover={{ y: -1 }}
                  onClick={() => setText(ex)}
                  className="rounded-xl border border-line bg-panel-2 px-3 py-1.5 text-left text-[12.5px] text-ink-2 transition-colors hover:border-brand/40 hover:text-ink"
                >
                  {ex}
                </motion.button>
              ))}
            </div>
          </div>
        </Card>

        <AnimatePresence mode="wait">
          {!caseId ? (
            <motion.div key="idle" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <Card className="flex h-full flex-col items-center justify-center p-10 text-center">
                <motion.div animate={{ rotate: [0, 8, -8, 0] }} transition={{ duration: 6, repeat: Infinity }} className="grid size-16 place-items-center rounded-2xl grad-bg text-white shadow-xl shadow-brand/30">
                  <Sparkles size={28} />
                </motion.div>
                <p className="mt-5 text-lg font-medium">Follow your request live</p>
                <p className="mt-1.5 max-w-sm text-sm text-ink-3">
                  After you send it, you will see it move through classification, the policy check, the solver and, if needed, negotiation.
                </p>
              </Card>
            </motion.div>
          ) : (
            <motion.div key={caseId} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
              <Card>
                <CardHeader
                  title={
                    <span className="flex items-center gap-2">
                      <span className="font-mono text-brand">{caseId}</span>
                      {detail && <StatusBadge status={detail.status} live={detail.running} />}
                    </span>
                  }
                  subtitle={detail?.running ? "Processing…" : "Done"}
                  action={
                    <Link to={`/requests/${caseId}`}>
                      <Button size="sm" icon={ArrowRight}>
                        Full audit
                      </Button>
                    </Link>
                  }
                />
                <div className="space-y-5 p-5">
                  <Lifecycle events={detail?.events ?? []} status={detail?.status ?? "received"} live={detail?.running} />
                  <AnimatePresence>
                    {done && detail?.reply && (
                      <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} className="rounded-2xl border border-brand/30 bg-brand/8 p-4">
                        <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-brand">
                          <CornerDownLeft size={13} /> Reply to you
                        </p>
                        <p className="mt-2 text-[14px] leading-relaxed">{detail.reply}</p>
                      </motion.div>
                    )}
                    {detail?.status === "negotiating" && (
                      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-3 rounded-2xl border border-warn/30 bg-warn/8 p-4 text-sm">
                        <LiveDot tone="warn" />
                        Your request clashes with someone else's. The negotiator has sent them solver-verified options and is waiting for a reply.
                        <Link to="/inbox" className="ml-auto shrink-0 text-brand hover:underline">
                          Inbox
                        </Link>
                      </motion.div>
                    )}
                  </AnimatePresence>
                  <div className="max-h-80 overflow-y-auto rounded-xl border border-line p-4">
                    <EventTimeline events={detail?.events ?? []} />
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => { setCaseId(null); setText(""); }}>
                    Write another
                  </Button>
                </div>
              </Card>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </>
  );
}
