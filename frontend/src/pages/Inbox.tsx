import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import { Bot, Check, Clock3, Inbox as InboxIcon, MessageSquareDashed, Undo2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { GroundedExplanation, OfferCard } from "../components/Negotiation";
import { Avatar, Badge, Button, Card, CardHeader, EmptyState, LiveDot, PageHeader, Tabs, Toast } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { ago } from "../lib/meta";
import type { InboxItem } from "../lib/types";

export default function Inbox() {
  const { user } = useAuth();
  const { data, refresh } = useApi(() => api.inbox(), [], 2000);
  const { data: inst } = useApi(() => api.instance(), []);
  const { data: auto, refresh: refreshAuto } = useApi(() => api.autopilot(), []);
  const [sel, setSel] = useState<string | null>(null);
  const [view, setView] = useState<"open" | "answered">("open");
  const [toast, setToast] = useState<string | null>(null);

  const items = (data ?? []).filter((i) => (view === "open" ? !i.reply : !!i.reply));
  useEffect(() => {
    if (!sel && items.length) setSel(items[0].id);
  }, [items, sel]);
  const current = (data ?? []).find((i) => i.id === sel) ?? null;
  const mine = user && current?.to === user.id;

  return (
    <>
      <PageHeader
        eyebrow="Negotiation"
        title="Inbox"
        subtitle="When your request clashes with someone else's, or theirs with yours, the negotiator writes to the person whose concession costs least, offering options the solver has already proved work."
        actions={
          user?.role !== "coordinator" &&
          auto && (
            <button
              onClick={async () => {
                await api.setAutopilot(user!.id, !auto[user!.id]);
                await refreshAuto();
              }}
              className={clsx(
                "flex items-center gap-2 rounded-xl border px-3 py-2 text-[13px] transition-colors",
                auto[user!.id] ? "border-ok/40 bg-ok/10 text-ok" : "border-line bg-panel-2 text-ink-2",
              )}
            >
              <Bot size={15} /> Autopilot {auto[user!.id] ? "on" : "off"}
              <span className={clsx("relative h-5 w-9 rounded-full transition-colors", auto[user!.id] ? "bg-ok" : "bg-line")}>
                <motion.span layout className="absolute top-0.5 size-4 rounded-full bg-white shadow" style={{ left: auto[user!.id] ? 18 : 2 }} />
              </span>
            </button>
          )
        }
      />
      <div className="grid gap-6 lg:grid-cols-[380px_minmax(0,1fr)]">
        <Card className="overflow-hidden">
          <div className="border-b border-line p-3">
            <Tabs
              tabs={[
                { id: "open", label: "Waiting", count: (data ?? []).filter((i) => !i.reply).length },
                { id: "answered", label: "Answered" },
              ]}
              value={view}
              onChange={(v) => {
                setView(v);
                setSel(null);
              }}
            />
          </div>
          <div className="max-h-[640px] divide-y divide-line overflow-y-auto">
            <AnimatePresence initial={false}>
              {items.map((i) => (
                <motion.button
                  layout
                  key={i.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, height: 0 }}
                  onClick={() => setSel(i.id)}
                  className={clsx("relative flex w-full gap-3 px-4 py-3.5 text-left transition-colors", sel === i.id ? "bg-brand/8" : "hover:bg-panel-2/60")}
                >
                  {sel === i.id && <motion.span layoutId="inbox-sel" className="absolute inset-y-0 left-0 w-0.5 grad-bg" />}
                  <Avatar name={i.to_name} id={i.to} size={34} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-[13.5px] font-medium">{user?.role === "coordinator" ? `To ${i.to_name}` : "Timetable negotiator"}</p>
                      {!i.reply && <LiveDot tone="warn" />}
                      <span className="ml-auto shrink-0 text-[11px] text-ink-3">{ago(i.created)}</span>
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-[12.5px] text-ink-3">{i.message.text.split("\n")[0]}</p>
                    <div className="mt-1.5 flex gap-1.5">
                      <Badge tone="muted">round {i.message.round}</Badge>
                      <Badge tone="brand">{i.message.offers.length} option{i.message.offers.length === 1 ? "" : "s"}</Badge>
                      {i.reply && <Badge tone={i.reply.decision === "accept" ? "ok" : "warn"}>{i.reply.decision}</Badge>}
                    </div>
                  </div>
                </motion.button>
              ))}
            </AnimatePresence>
            {!items.length && <EmptyState icon={InboxIcon} title={view === "open" ? "Nothing waiting" : "No answered messages"} text="Messages appear here when a request you're part of needs a concession." />}
          </div>
        </Card>

        <AnimatePresence mode="wait">
          {current && inst ? (
            <motion.div key={current.id} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }}>
              <Thread
                item={current}
                mine={!!mine}
                canSimulate={!!mine || user?.role === "coordinator"}
                days={inst.calendar.days}
                slots={inst.slots}
                onDone={async (msg) => {
                  setToast(msg);
                  await refresh();
                }}
              />
            </motion.div>
          ) : (
            <Card className="grid place-items-center">
              <EmptyState icon={MessageSquareDashed} title="Select a message" />
            </Card>
          )}
        </AnimatePresence>
      </div>
      <Toast message={toast} onDone={() => setToast(null)} />
    </>
  );
}

function Thread({
  item,
  mine,
  canSimulate,
  days,
  slots,
  onDone,
}: {
  item: InboxItem;
  mine: boolean;
  canSimulate: boolean;
  days: string[];
  slots: { slot: number; label: string }[];
  onDone: (msg: string) => Promise<void>;
}) {
  const [choice, setChoice] = useState<string | null>(null);
  const [mode, setMode] = useState<"pick" | "counter">("pick");
  const [cDays, setCDays] = useState<string[]>([]);
  const [from, setFrom] = useState(5);
  const [to, setTo] = useState(7);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const m = item.message;
  const answered = !!item.reply;

  const act = async (label: string, fn: () => Promise<unknown>, msg: string) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
      await onDone(msg);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={`Round ${m.round}: a timetable conflict${mine ? " needs your answer" : ` for ${item.to_name}`}`}
          subtitle={
            <span className="flex flex-wrap items-center gap-2">
              {item.case && (
                <Link to={`/requests/${item.case}`} className="font-mono text-brand hover:underline">
                  {item.case}
                </Link>
              )}
              <span className="flex items-center gap-1">
                <Clock3 size={12} /> reply by {new Date(item.deadline).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            </span>
          }
        />
        <div className="space-y-5 p-5">
          <p className="whitespace-pre-line text-[14px] leading-relaxed">{m.text.split("\n\nOptions:")[0]}</p>
          <div className="grid gap-3 md:grid-cols-3">
            {m.offers.map((o) => (
              <OfferCard
                key={o.key}
                offer={o}
                selected={choice === o.key && mode === "pick"}
                accepted={item.reply?.decision === "accept" && item.reply.choice === o.key}
                onSelect={mine && !answered ? () => { setChoice(o.key); setMode("pick"); } : undefined}
              />
            ))}
          </div>

          {answered ? (
            <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} className="flex items-center gap-3 rounded-2xl border border-ok/30 bg-ok/8 p-4 text-sm">
              <Check size={18} className="text-ok" />
              <span>
                Answered{item.answered_by === "simulator" ? " by the simulator" : item.answered_by === "deadline" ? " (deadline passed)" : ""}:{" "}
                <span className="font-medium">
                  {item.reply?.decision}
                  {item.reply?.choice ? ` ${item.reply.choice}` : ""}
                </span>
                {item.reply?.text ? ` · “${item.reply.text}”` : ""}
              </span>
            </motion.div>
          ) : (
            <div className="space-y-4">
              {mine && (
                <AnimatePresence>
                  {mode === "counter" && (
                    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
                      <div className="rounded-2xl border border-warn/30 bg-warn/5 p-4">
                        <p className="text-[13px] font-medium">Which days and times would work instead?</p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {days.map((d) => (
                            <button
                              key={d}
                              onClick={() => setCDays((xs) => (xs.includes(d) ? xs.filter((x) => x !== d) : [...xs, d]))}
                              className={clsx("rounded-xl border px-3 py-1.5 text-[13px] transition-colors", cDays.includes(d) ? "border-warn bg-warn/15 text-ink" : "border-line text-ink-2")}
                            >
                              {d}
                            </button>
                          ))}
                        </div>
                        <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px]">
                          from
                          <select value={from} onChange={(e) => setFrom(+e.target.value)} className="rounded-lg border border-line bg-panel px-2 py-1">
                            {slots.map((s) => (
                              <option key={s.slot} value={s.slot}>
                                {s.label}
                              </option>
                            ))}
                          </select>
                          until the end of
                          <select value={to} onChange={(e) => setTo(+e.target.value)} className="rounded-lg border border-line bg-panel px-2 py-1">
                            {slots.map((s) => (
                              <option key={s.slot} value={s.slot}>
                                {s.label}
                              </option>
                            ))}
                          </select>
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              )}
              <div className="flex flex-wrap items-center gap-2">
                {mine && (
                  <>
                    <Button
                      variant="success"
                      icon={Check}
                      disabled={!choice || mode !== "pick"}
                      loading={busy === "accept"}
                      onClick={() => act("accept", () => api.reply(item.id, { decision: "accept", choice: choice!, text: `Option ${choice} works for me.` }), `Accepted option ${choice}. The solver re-solves now.`)}
                    >
                      Accept {choice ?? "an option"}
                    </Button>
                    {mode === "counter" ? (
                      <Button
                        icon={Undo2}
                        disabled={!cDays.length || to < from}
                        loading={busy === "counter"}
                        onClick={() =>
                          act(
                            "counter",
                            () =>
                              api.reply(item.id, {
                                decision: "counter",
                                counter_days: cDays,
                                counter_slots: Array.from({ length: to - from + 1 }, (_, i) => from + i),
                                text: `${cDays.join(", ")} from ${slots[from].label} would work.`,
                              }),
                            "Counter-offer sent. Your constraint is replaced and the solver tries again.",
                          )
                        }
                      >
                        Send counter-offer
                      </Button>
                    ) : (
                      <Button icon={Undo2} onClick={() => setMode("counter")}>
                        Suggest other times
                      </Button>
                    )}
                    <Button
                      variant="danger"
                      icon={X}
                      loading={busy === "reject"}
                      onClick={() => act("reject", () => api.reply(item.id, { decision: "reject", text: "None of these work for me." }), "Declined. The negotiator will ask again or move on.")}
                    >
                      Decline
                    </Button>
                  </>
                )}
                {canSimulate && (
                  <Button variant="ghost" icon={Bot} loading={busy === "sim"} className="ml-auto" onClick={() => act("sim", () => api.simulate(item.id), "The simulated stakeholder answered.")}>
                    Let the simulator answer
                  </Button>
                )}
              </div>
              {error && <p className="rounded-xl bg-bad/10 px-3 py-2 text-sm text-bad">{error}</p>}
            </div>
          )}
        </div>
      </Card>
      <Card>
        <CardHeader title="Why you are seeing this" subtitle="Every sentence of the explanation must trace to a fact below; private reasons are never among them" />
        <div className="p-5">
          <GroundedExplanation m={m} />
        </div>
      </Card>
    </div>
  );
}
