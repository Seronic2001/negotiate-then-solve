import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import { Bot, Check, Clock3, Inbox as InboxIcon, MessageSquareDashed, Undo2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { GroundedExplanation, OfferCard } from "../components/Negotiation";
import { Avatar, Button, Card, CardHeader, Collapse, EmptyState, LiveDot, PageHeader, Tabs, Toast } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { ago } from "../lib/meta";
import { study as studyApi } from "../lib/study";
import type { InboxItem } from "../lib/types";
import { useStudySession } from "../components/StudyBanner";
import { RatingForm } from "../components/Rating";

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
        title="Inbox"
        subtitle="Messages from the negotiator when a request clashes with yours."
        actions={
          user?.role !== "coordinator" &&
          auto && (
            <button
              onClick={async () => {
                await api.setAutopilot(user!.id, !auto[user!.id]);
                await refreshAuto();
              }}
              title="Let the simulator answer your messages automatically"
              className="flex items-center gap-2.5 text-[13px] text-ink-2"
            >
              <Bot size={15} className="text-ink-3" /> Answer automatically
              <span className={clsx("relative h-[18px] w-8 rounded-full transition-colors", auto[user!.id] ? "bg-ok" : "bg-line")}>
                <span className="absolute top-[3px] size-3 rounded-full bg-panel transition-[left]" style={{ left: auto[user!.id] ? 17 : 3 }} />
              </span>
            </button>
          )
        }
      />
      <div className="grid gap-6 lg:grid-cols-[340px_minmax(0,1fr)]">
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
          <div className="max-h-[680px] divide-y divide-line overflow-y-auto">
            {items.map((i) => (
                <button
                  key={i.id}
                  onClick={() => setSel(i.id)}
                  className={clsx("relative flex w-full gap-3 px-4 py-3 text-left", sel === i.id ? "bg-panel-2" : "hover:bg-panel-2/50")}
                >
                  {sel === i.id && <span className="absolute inset-y-0 left-0 w-0.5 bg-brand" />}
                  <Avatar name={i.to_name} id={i.to} size={30} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-[13.5px] font-medium">{user?.role === "coordinator" ? `To ${i.to_name}` : "Timetable office"}</p>
                      {!i.reply && <LiveDot tone="warn" />}
                      <span className="ml-auto shrink-0 text-[11px] text-ink-3">{ago(i.created)}</span>
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-[12.5px] text-ink-3">{i.message.text.split("\n")[0]}</p>
                    <p className="mt-1 text-[12px] text-ink-3">
                      {i.message.offers.length} option{i.message.offers.length === 1 ? "" : "s"}
                      {i.message.round > 1 ? ` · round ${i.message.round}` : ""}
                      {i.reply && <span className={i.reply.decision === "accept" ? "text-ok" : "text-warn"}> · {i.reply.decision}</span>}
                    </p>
                  </div>
                </button>
              ))}
            {!items.length && <EmptyState icon={InboxIcon} title={view === "open" ? "Nothing waiting" : "No answered messages"} text="Messages arrive here when a request clashes with your timetable." />}
          </div>
        </Card>

        <AnimatePresence mode="wait">
          {current && inst ? (
            <motion.div key={current.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.12 }}>
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
            <Card className="hidden place-items-center lg:grid">
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
          title={mine ? "A clash with your timetable" : `A clash for ${item.to_name}`}
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
            <div className="flex items-center gap-2.5 rounded-md border border-line bg-panel-2 px-4 py-3 text-[13.5px]">
              <Check size={16} className="text-ok" />
              <span>
                Answered{item.answered_by === "simulator" ? " by the simulator" : item.answered_by === "deadline" ? " (deadline passed)" : ""}:{" "}
                <span className="font-medium">
                  {item.reply?.decision}
                  {item.reply?.choice ? ` ${item.reply.choice}` : ""}
                </span>
                {item.reply?.text ? ` · “${item.reply.text}”` : ""}
              </span>
            </div>
          ) : (
            <div className="space-y-4">
              {mine && (
                <AnimatePresence>
                  {mode === "counter" && (
                    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
                      <div className="rounded-md border border-line bg-panel-2 p-4">
                        <p className="text-[13px] font-medium">Which days and times would work instead?</p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {days.map((d) => (
                            <button
                              key={d}
                              onClick={() => setCDays((xs) => (xs.includes(d) ? xs.filter((x) => x !== d) : [...xs, d]))}
                              className={clsx("rounded-md border px-3 py-1 text-[13px]", cDays.includes(d) ? "border-brand bg-brand text-panel" : "border-line bg-panel text-ink-2")}
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
                      variant="primary"
                      icon={Check}
                      disabled={!choice || mode !== "pick"}
                      loading={busy === "accept"}
                      onClick={() => act("accept", () => api.reply(item.id, { decision: "accept", choice: choice!, text: `Option ${choice} works for me.` }), `Accepted option ${choice}. The solver re-solves now.`)}
                    >
                      {choice ? `Accept option ${choice}` : "Pick an option"}
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
                        Suggest another time
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
                    Simulate a reply
                  </Button>
                )}
              </div>
              {error && <p className="rounded-md bg-bad/10 px-3 py-2 text-sm text-bad">{error}</p>}
              {mine && <OwnWords item={item} onDone={onDone} />}
            </div>
          )}
        </div>
      </Card>
      {mine && <RateMessage item={item} />}
      <Collapse title="Why these options (the facts behind the message)">
          <GroundedExplanation m={m} />
        </Collapse>
    </div>
  );
}

/** Reply in your own words: the reply parser reads it into one answer, which the sender confirms before it is sent. */
function OwnWords({ item, onDone }: { item: InboxItem; onDone: (msg: string) => Promise<void> }) {
  const study = useStudySession();
  const [text, setText] = useState("");
  const [reading, setReading] = useState<{ reading: string; parser: string | null } | null>(null);
  const [rejected, setRejected] = useState(false);
  const [busy, setBusy] = useState<"check" | "send" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const check = async () => {
    setBusy("check");
    setError(null);
    setRejected(false);
    try {
      setReading(await api.replyText(item.id, text, true));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const send = async () => {
    setBusy("send");
    setError(null);
    try {
      const got = await api.replyText(item.id, text, false);
      if (study) await studyApi.live({ kind: "reply", item: item.id, text, reading: got.reading, confirmed: true });
      await onDone("Reply sent. The negotiator continues with your answer.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const wrong = async () => {
    setRejected(true);
    if (study && reading) await studyApi.live({ kind: "reply", item: item.id, text, reading: reading.reading, confirmed: false });
  };

  return (
    <div className="rounded-md border border-line p-4">
      <p className="text-[13px] font-medium">Or reply in your own words</p>
      <textarea
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setReading(null);
        }}
        rows={2}
        placeholder="e.g. Wednesday works for me, but not before 11."
        className="mt-2 w-full resize-none rounded-md border border-line bg-panel p-2.5 text-[13.5px] outline-none focus:border-brand/60"
      />
      {!reading ? (
        <Button size="sm" className="mt-2" disabled={!text.trim()} loading={busy === "check"} onClick={check}>
          Check how it is read
        </Button>
      ) : (
        <div className="mt-2 space-y-2">
          <p className="rounded-md bg-panel-2 px-3 py-2 text-[13.5px]">
            <span className="text-ink-3">The system reads this as: </span>
            {reading.reading}
          </p>
          {rejected ? (
            <p className="text-[13px] text-ink-2">Thanks, noted. Rephrase it above, or answer with the buttons.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="primary" icon={Check} loading={busy === "send"} onClick={send}>
                Yes, send it
              </Button>
              <Button size="sm" icon={X} onClick={wrong}>
                No, that is not what I meant
              </Button>
            </div>
          )}
          {reading.parser && <p className="text-[11.5px] text-ink-3">Read by: {reading.parser}</p>}
        </div>
      )}
      {error && <p className="mt-2 text-[13px] text-bad">{error}</p>}
    </div>
  );
}

/** Pilot participants rate the message they received, as in the study's rating task. */
function RateMessage({ item }: { item: InboxItem }) {
  const study = useStudySession();
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!study) return null;
  return (
    <Card>
      <CardHeader title="Study: rate this message" subtitle="How it reads to you, whatever you answered" />
      <div className="p-5">
        {saved ? (
          <p className="flex items-center gap-2 text-[13.5px] text-ok">
            <Check size={15} /> Saved. Thank you.
          </p>
        ) : (
          <RatingForm
            busy={busy}
            submitLabel="Save rating"
            onSave={async (value) => {
              setBusy(true);
              await studyApi.live({ kind: "rating", item: item.id, text: item.message.text, value });
              setBusy(false);
              setSaved(true);
            }}
          />
        )}
      </div>
    </Card>
  );
}
