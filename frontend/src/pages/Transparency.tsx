import clsx from "clsx";
import { AnimatePresence, motion, useInView, useReducedMotion } from "framer-motion";
import {
  ArrowRight,
  BadgeCheck,
  Bell,
  Brain,
  CalendarCheck,
  Check,
  CircleSlash,
  Eye,
  FileSearch,
  Layers,
  Lock,
  MessageSquareText,
  Pause,
  PenLine,
  Play,
  ScanText,
  Scale,
  ShieldCheck,
  Users,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Card, CardHeader, PageHeader, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";
import { TIER } from "../lib/meta";
import type { Transparency as Data } from "../lib/types";

/* The How it works page of the agentic demo: the agent loop shown working. A chat message travels through the
 * loop (each stage plays a small scene of the agent's tool calls), a clash plays out step by step, and what
 * bounds the agent (tiers, its tools, its model and budgets, the guarantees) is drawn rather than listed. Every
 * caption comes from the server (/api/transparency), so the words stay those of the running system; the scenes
 * are illustrations. */

/** The page's colours: the app's tones plus violet and teal for the scenes. */
const HUE = {
  brand: { text: "text-brand", bg: "bg-brand/12", dot: "bg-brand", border: "border-brand" },
  ok: { text: "text-ok", bg: "bg-ok/12", dot: "bg-ok", border: "border-ok" },
  warn: { text: "text-warn", bg: "bg-warn/15", dot: "bg-warn", border: "border-warn" },
  bad: { text: "text-bad", bg: "bg-bad/12", dot: "bg-bad", border: "border-bad" },
  info: { text: "text-info", bg: "bg-info/12", dot: "bg-info", border: "border-info" },
  muted: { text: "text-ink-2", bg: "bg-ink-3/12", dot: "bg-ink-3", border: "border-ink-3" },
  violet: { text: "text-violet", bg: "bg-violet/12", dot: "bg-violet", border: "border-violet" },
  teal: { text: "text-teal", bg: "bg-teal/12", dot: "bg-teal", border: "border-teal" },
} as const;

const STAGE_ICON: LucideIcon[] = [ScanText, FileSearch, PenLine, Workflow, Users, CalendarCheck];
const STAGE_MS = 8500; // each scene's last step lands ~2.5 s before the next stage

/** ``count`` phases, one every ``ms``, restarting when the component mounts; the last phase at once when
 * motion is reduced. */
function usePhases(count: number, ms: number): number {
  const reduce = useReducedMotion();
  const [phase, setPhase] = useState(reduce ? count - 1 : 0);
  useEffect(() => {
    if (reduce) return;
    const ids = Array.from({ length: count - 1 }, (_, i) => window.setTimeout(() => setPhase(i + 1), ms * (i + 1)));
    return () => ids.forEach(clearTimeout);
  }, [count, ms, reduce]);
  return phase;
}

/** A section that fades up the first time it scrolls into view. */
function Reveal({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.45, delay, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  );
}

export default function Transparency() {
  const { data } = useApi(() => api.transparency(), []);
  if (!data) return <Skeleton className="h-[600px]" />;
  return (
    <>
      <PageHeader
        title="How it works"
        subtitle="Follow one chat message through the agent loop to a published timetable. The model reads and drafts through tools; the solver checks; people agree and approve."
      />
      <Pipeline stages={data.lifecycle} />
      <Reveal className="mt-6">
        <NegotiationStory ladder={data.ladder} settings={data.negotiation} />
      </Reveal>
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <Reveal>
          <Tiers tiers={data.tiers} />
        </Reveal>
        <Reveal delay={0.08}>
          <Tools tools={data.agent.tools} />
        </Reveal>
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Reveal>
          <AgentModel agent={data.agent} systemOne={data.system_one} />
        </Reveal>
        <Reveal delay={0.08}>
          <Safety items={data.safety} />
        </Reveal>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------------------------------------------------
 * The pipeline: six stages, a message travelling between them, a scene per stage */

function Pipeline({ stages }: { stages: Data["lifecycle"] }) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { margin: "-80px" });
  const [active, setActive] = useState(0);
  const [playing, setPlaying] = useState(!reduce);
  useEffect(() => {
    if (!playing || !inView) return;
    const id = window.setTimeout(() => setActive((a) => (a + 1) % stages.length), STAGE_MS);
    return () => clearTimeout(id);
  }, [playing, inView, active, stages.length]);
  const stage = stages[active];
  const Scene = SCENES[active] ?? (() => null);

  return (
    <Card className="overflow-hidden">
      <CardHeader
        icon={MessageSquareText}
        title="What happens to a chat message"
        subtitle="Click a stage to look closer"
        action={
          <button
            onClick={() => setPlaying((p) => !p)}
            className="flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-[12px] text-ink-2 hover:bg-panel-2"
          >
            {playing ? <Pause size={12} /> : <Play size={12} />}
            {playing ? "Pause" : "Play"}
          </button>
        }
      />
      <div ref={ref} className="px-5 pt-6">
        <div className="relative">
          {/* the track and the message moving along it */}
          <div className="absolute top-5 right-[8.33%] left-[8.33%] hidden h-0.5 rounded-full bg-line sm:block" />
          <motion.div
            className="absolute top-5 left-[8.33%] hidden h-0.5 rounded-full bg-brand sm:block"
            animate={{ width: `${(active / (stages.length - 1)) * 83.33}%` }}
            transition={{ duration: reduce ? 0 : 0.6, ease: "easeInOut" }}
          />
          <ol className="relative grid grid-cols-3 gap-y-4 sm:grid-cols-6">
            {stages.map((s, i) => {
              const Icon = STAGE_ICON[i] ?? Check;
              const on = i === active;
              const done = i < active;
              return (
                <li key={s.name} className="flex justify-center">
                  <button
                    onClick={() => {
                      setActive(i);
                      setPlaying(false);
                    }}
                    className="group flex flex-col items-center gap-2 text-center"
                  >
                    <motion.span
                      animate={{ scale: on ? 1.12 : 1 }}
                      className={clsx(
                        "relative grid size-10 place-items-center rounded-full border-2 bg-panel transition-colors",
                        on ? "border-brand text-brand" : done ? "border-brand/60 text-brand/80" : "border-line text-ink-3 group-hover:text-ink",
                      )}
                    >
                      <Icon size={17} />
                      {on && !reduce && (
                        <motion.span
                          className="absolute inset-0 rounded-full border-2 border-brand"
                          initial={{ opacity: 0.7, scale: 1 }}
                          animate={{ opacity: 0, scale: 1.6 }}
                          transition={{ duration: 1.4, repeat: Infinity }}
                        />
                      )}
                    </motion.span>
                    <span className={clsx("text-[12px] leading-tight font-medium", on ? "text-ink" : "text-ink-3")}>{s.name}</span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
        {/* progress of the current stage while playing */}
        <div className="mt-5 h-0.5 overflow-hidden rounded-full bg-panel-2">
          {playing && inView && (
            <motion.div
              key={active}
              className="h-full bg-brand/50"
              initial={{ width: 0 }}
              animate={{ width: "100%" }}
              transition={{ duration: STAGE_MS / 1000, ease: "linear" }}
            />
          )}
        </div>
      </div>
      <div className="grid gap-6 p-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <motion.div key={`t${active}`} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.3 }}>
            <p className="text-[11.5px] font-medium tracking-wide text-brand uppercase">
              Stage {active + 1} of {stages.length}
            </p>
            <h3 className="mt-1 font-serif text-[22px] font-semibold">{stage.name}</h3>
            <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">{stage.text}</p>
        </motion.div>
        <div className="min-h-[230px] rounded-lg border border-line bg-panel-2/50 p-4">
          <Scene key={active} />
        </div>
      </div>
    </Card>
  );
}

function Chip({ children, tone = "brand", delay = 0, show = true }: { children: ReactNode; tone?: keyof typeof HUE; delay?: number; show?: boolean }) {
  return (
    <AnimatePresence>
      {show && (
        <motion.span
          initial={{ opacity: 0, scale: 0.85 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay, type: "spring", stiffness: 380, damping: 24 }}
          className={clsx("inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] font-medium", HUE[tone].bg, HUE[tone].text)}
        >
          {children}
        </motion.span>
      )}
    </AnimatePresence>
  );
}

/* The agent's scenes: the same case, told as the agent's tool calls. */

/** A tool call and what came back, as one line of the agent's work. */
function Call({ name, args, result, ok = true, show, delay = 0 }: { name: string; args: string; result?: string; ok?: boolean; show: boolean; delay?: number }) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay, duration: 0.3 }}
          className="rounded-md border border-line bg-panel px-2.5 py-1.5 text-[12px]"
        >
          <p className="flex items-center gap-1.5">
            {ok ? <Check size={12} className="shrink-0 text-ok" /> : <X size={12} className="shrink-0 text-bad" />}
            <span className="font-mono text-[11.5px] text-brand">{name}</span>
            <span className="truncate font-mono text-[11px] text-ink-3">({args})</span>
          </p>
          {result && <p className={clsx("mt-0.5 pl-[18px] text-[11.5px] leading-snug", ok ? "text-ink-2" : "text-bad")}>{result}</p>}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function AgentReadScene() {
  const phase = usePhases(4, 1600);
  return (
    <div className="space-y-3 text-[13px]">
      <div className="rounded-md border border-line bg-panel p-3">
        <p className="mb-1.5 text-[11px] text-ink-3">Dr. Das writes in the chat</p>
        <p className="leading-relaxed">my DL prac has to be on thu at 2pm in wk 5, the external examiner is visiting</p>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Chip show={phase >= 1} tone="muted">
          sender: Dr. Das
        </Chip>
        <Chip show={phase >= 1} delay={0.12} tone="muted">
          week 4 of 16
        </Chip>
        <Chip show={phase >= 1} delay={0.24} tone="muted">
          + the last 4 messages and what came of them
        </Chip>
      </div>
      <div className="flex items-center gap-2 text-ink-3">
        <ArrowRight size={14} />
        <span className="text-[11.5px]">System One picks the tools to offer</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Chip show={phase >= 2} tone="warn">
          a change, not a question
        </Chip>
        <Chip show={phase >= 3} delay={0.1}>
          <Layers size={11} /> every tool: read · draft · check · talk · end
        </Chip>
      </div>
    </div>
  );
}

function LookupScene() {
  const phase = usePhases(4, 1500);
  return (
    <div className="space-y-1.5">
      <Call show={phase >= 0} name="classes_of" args='teacher="me", week=5' result="Digital Logic practical · Section 3 · Mon 11 am–1 pm · Lab 3" />
      <Call show={phase >= 1} name="who_is_free" args='"Section 3", Thu, 2 pm, week 5' result="Section 3 has Algorithms practical (Dr. Sharma), Lab 3" />
      <Call show={phase >= 2} name="find" args='"DL lab"' ok={false} result='No class "DL lab". Did you mean: Digital Logic practical?' />
      <Chip show={phase >= 3} tone="info">
        <Eye size={11} /> names in, names out; a wrong name is refused with what it might mean
      </Chip>
    </div>
  );
}

function DraftScene() {
  const phase = usePhases(4, 1600);
  return (
    <div className="space-y-3 text-[13px]">
      <Call show={phase >= 0} name="move_class" args='"Digital Logic practical", to_day="Thu", to_hour="2 pm", week=5' result="Drafted: the Digital Logic practical in week 5 on Thursday at 2 pm" />
      <motion.div
        animate={{ opacity: phase >= 1 ? 1 : 0.4 }}
        className="relative rounded-md border border-dashed border-brand/60 bg-brand/5 p-3"
      >
        <p className="flex items-center gap-1.5 text-[11px] font-medium text-brand">
          <Lock size={11} /> Private draft · nothing here is in the timetable
        </p>
        <ul className="mt-1.5 space-y-1 text-[12.5px] text-ink-2">
          <li className="flex gap-1.5">
            <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-brand/60" /> Digital Logic practical (Section 3) in week 5: Thursday 2 pm, required
          </li>
        </ul>
      </motion.div>
      <div className="flex flex-wrap gap-1.5">
        <Chip show={phase >= 2} tone="ok">
          <ShieldCheck size={11} /> his own class: allowed
        </Chip>
        <Chip show={phase >= 3} delay={0.1} tone="bad">
          <CircleSlash size={11} /> a colleague's class: refused
        </Chip>
      </div>
    </div>
  );
}

function AgentCheckScene() {
  const phase = usePhases(4, 1700);
  return (
    <div className="space-y-2 text-[13px]">
      <Call show={phase >= 0} name="check_draft" args="" ok={false} result="Does not fit: CP-SAT finds no repair of week 5 that keeps every rule." />
      <AnimatePresence>
        {phase >= 1 && (
          <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="rounded-md border border-bad/40 bg-bad/5 p-2.5 text-[12.5px]">
            <p className="text-[11px] font-medium text-bad">It clashes with</p>
            <p className="mt-1">
              <span className="font-mono text-[11px] text-ink-3">rule 2 · </span>Algorithms practical (Section 3) in Lab 3 on Thursday at 2 pm
            </p>
            <p className="mt-0.5 text-[11.5px] text-ink-3">owner: Dr. Sharma · firm (Tier 4) · has given way 0 times this term</p>
            <p className="mt-1">
              <span className="font-mono text-[11px] text-ink-3">rule 1 · </span>the draft's: Digital Logic practical Thu 2 pm, week 5
            </p>
          </motion.div>
        )}
      </AnimatePresence>
      <div className="flex flex-wrap gap-1.5">
        <Chip show={phase >= 2} tone="warn">
          <Users size={11} /> a teacher's rule: can be asked
        </Chip>
        <Chip show={phase >= 3} delay={0.1} tone="muted">
          <Lock size={11} /> the office's rules: never offered
        </Chip>
      </div>
    </div>
  );
}

function AskScene() {
  const phase = usePhases(5, 1500);
  return (
    <div className="space-y-2 text-[13px]">
      <Call show={phase >= 0} name="make_offer" args='to="Dr. Sharma", rule=2' />
      <AnimatePresence>
        {phase >= 1 && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="max-w-[88%] rounded-lg rounded-bl-sm border border-line bg-panel px-3 py-2 text-[12.5px]">
            <p className="mb-0.5 text-[10.5px] text-ink-3">To Dr. Sharma's inbox</p>
            Could your Algorithms practical give way in week 5 only, so Dr. Das's Digital Logic practical can be in Lab 3 on Thursday at 2 pm?
          </motion.div>
        )}
        {phase >= 2 && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="ml-auto max-w-[70%] rounded-lg rounded-br-sm bg-brand px-3 py-2 text-[12.5px] text-white">
            Yes, this once in week 5.
          </motion.div>
        )}
      </AnimatePresence>
      <Call show={phase >= 3} name="check_draft" args="" result="Fits. Moves: Algorithms practical to Thu 3 pm (Dr. Sharma), week 5 only." />
      <Call show={phase >= 4} name="submit" args='message="…"' result="Sent to the timetable office for approval." />
    </div>
  );
}

function AgentPublishScene() {
  const phase = usePhases(4, 1500);
  const people = ["Dr. Das", "Dr. Sharma", "Section 3"];
  return (
    <div className="flex h-full flex-col items-center gap-4 text-[13px]">
      <div className="relative w-full max-w-sm rounded-md border border-line bg-panel p-3">
        <p className="text-[11px] text-ink-3">A change is waiting for your approval</p>
        <p className="mt-1">Week 5: Digital Logic practical to Thu 2 pm; Algorithms practical to Thu 3 pm</p>
        <p className="mt-1 text-[11.5px] text-ink-3">Drafted by the assistant, checked by the solver, Dr. Sharma agreed</p>
        <motion.span
          animate={phase === 1 ? { scale: [1, 0.92, 1] } : {}}
          className={clsx(
            "mt-2 inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[12px] font-medium",
            phase >= 1 ? "bg-ok text-white" : "border border-line text-ink-2",
          )}
        >
          <Check size={12} /> Approve
        </motion.span>
        <AnimatePresence>
          {phase >= 2 && (
            <motion.span
              initial={{ opacity: 0, scale: 1.8, rotate: -18 }}
              animate={{ opacity: 1, scale: 1, rotate: -8 }}
              transition={{ type: "spring", stiffness: 300, damping: 15 }}
              className="absolute right-3 bottom-3 rounded border-2 border-ok px-2 py-0.5 font-mono text-[11px] font-semibold text-ok"
            >
              v14 PUBLISHED
            </motion.span>
          )}
        </AnimatePresence>
      </div>
      <Chip show={phase >= 2} tone="ok">
        <ShieldCheck size={11} /> commit gate: every change checked again by the kernel
      </Chip>
      <div className="flex w-full max-w-sm justify-around">
        {people.map((p, i) => (
          <div key={p} className="flex flex-col items-center gap-1">
            <motion.span
              animate={phase >= 3 ? { y: [0, -6, 0] } : {}}
              transition={{ delay: i * 0.15, duration: 0.5 }}
              className={clsx("relative grid size-9 place-items-center rounded-full", phase >= 3 ? "bg-brand/15 text-brand" : "bg-panel-2 text-ink-3")}
            >
              <Users size={15} />
              {phase >= 3 && (
                <motion.span
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ delay: i * 0.15 }}
                  className="absolute -top-1 -right-1 grid size-4 place-items-center rounded-full bg-bad text-[9px] font-bold text-white"
                >
                  1
                </motion.span>
              )}
            </motion.span>
            <span className="text-[11px] text-ink-3">{p}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const SCENES = [AgentReadScene, LookupScene, DraftScene, AgentCheckScene, AskScene, AgentPublishScene];

/* ---------------------------------------------------------------------------------------------------------
 * The ladder and a negotiation played round by round */

type Beat = { who: "system" | "owner" | "note"; text: string; rung: number; tone?: keyof typeof HUE; icon?: LucideIcon };
const STORY: Beat[] = [
  { who: "note", text: "Dr. Das: my Digital Logic practical has to be in Lab 3 on Thursday at 2 pm in week 5.", rung: 0 },
  { who: "note", text: "move_class, then check_draft: no repair fits. It clashes with rule 2, Dr. Sharma's Algorithms practical in Lab 3 (firm).", rung: 0, icon: X, tone: "bad" },
  { who: "note", text: "The request is clear, so the sender is not asked. Rule 2 is a teacher's, so its owner can be.", rung: 1 },
  { who: "system", text: "Dr. Sharma, could your Algorithms practical give way in week 5 only, so Dr. Das's Digital Logic practical can be in Lab 3 on Thursday at 2 pm?", rung: 2 },
  { who: "owner", text: "Not at 2, but I could take my practical at 3 pm that week.", rung: 2 },
  { who: "note", text: "A counter-offer: the waiver goes into the draft with the Algorithms practical at 3 pm, week 5 only.", rung: 2, icon: Bell, tone: "warn" },
  { who: "note", text: "check_draft again: it fits, nothing else moves. submit: waiting for the timetable office.", rung: 2, icon: BadgeCheck, tone: "ok" },
  { who: "note", text: "Had Dr. Sharma said no, or had it been an office rule, the agent would escalate it with what it tried.", rung: 3, icon: CircleSlash },
];

function NegotiationStory({ ladder, settings }: { ladder: Data["ladder"]; settings: Data["negotiation"] }) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { margin: "-80px" });
  const [shown, setShown] = useState(reduce ? STORY.length : 0);
  useEffect(() => {
    if (!inView || reduce) return;
    const id = window.setTimeout(() => setShown((n) => (n >= STORY.length + 2 ? 0 : n + 1)), shown === 0 ? 600 : 2600);
    return () => clearTimeout(id);
  }, [inView, shown, reduce]);
  const beats = STORY.slice(0, shown);
  const rung = beats.length ? beats[beats.length - 1].rung : -1;

  return (
    <Card>
      <CardHeader icon={Workflow} title="How the agent gets out of a clash" subtitle="The cheapest way out is tried first; people are asked only when the solver cannot do it alone" />
      <div ref={ref} className="grid gap-6 p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        {/* a staircase: each rung involves more people */}
        <ol className="space-y-2">
          {ladder.map((s, i) => {
            const on = i === rung;
            const past = i < rung;
            return (
              <motion.li
                key={s.step}
                animate={{ opacity: rung === -1 || on || past ? 1 : 0.45 }}
                style={{ marginLeft: `${i * 6}%` }}
                className={clsx(
                  "rounded-lg border p-3 transition-colors",
                  on ? "border-brand bg-brand/8" : past ? "border-line bg-panel-2/40" : "border-line",
                )}
              >
                <p className="flex items-center gap-2 text-[13.5px] font-medium">
                  <span
                    className={clsx(
                      "grid size-6 shrink-0 place-items-center rounded-full text-[12px] font-semibold",
                      on ? "bg-brand text-white" : past ? "bg-ok/15 text-ok" : "border border-line text-ink-3",
                    )}
                  >
                    {past ? <Check size={12} /> : s.step}
                  </span>
                  {s.name}
                  {on && (
                    <motion.span layoutId="here" className="ml-auto text-[11px] font-normal text-brand">
                      now
                    </motion.span>
                  )}
                </p>
                <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-2">{s.text}</p>
              </motion.li>
            );
          })}
        </ol>
        <div className="flex min-w-0 flex-col">
          <div className="flex min-h-[340px] flex-1 flex-col gap-2 rounded-lg border border-line bg-panel-2/40 p-4">
            <AnimatePresence initial={false}>
              {beats.map((b, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 10, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ type: "spring", stiffness: 320, damping: 26 }}
                  className={clsx("flex", b.who === "owner" ? "justify-end" : b.who === "note" ? "justify-center" : "justify-start")}
                >
                  {b.who === "note" ? (
                    <span className={clsx("flex max-w-[92%] items-center gap-1.5 text-center text-[12px]", b.tone ? HUE[b.tone].text : "text-ink-3")}>
                      {b.icon && <b.icon size={12} className="shrink-0" />}
                      {b.text}
                    </span>
                  ) : (
                    <div
                      className={clsx(
                        "max-w-[82%] rounded-lg px-3 py-2 text-[13px]",
                        b.who === "owner" ? "rounded-br-sm bg-brand text-white" : "rounded-bl-sm border border-line bg-panel",
                      )}
                    >
                      <p className={clsx("mb-0.5 text-[10.5px]", b.who === "owner" ? "text-white/75" : "text-ink-3")}>
                        {b.who === "owner" ? "Dr. Sharma" : "Timetable assistant"}
                      </p>
                      <span className="flex items-start gap-1.5">
                        {b.icon && <b.icon size={13} className="mt-0.5 shrink-0" />}
                        {b.text}
                      </span>
                    </div>
                  )}
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
          <p className="mt-4 text-[11.5px] text-ink-3">Each episode's budget</p>
          <dl className="mt-1.5 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {Object.entries(settings).map(([k, v]) => (
              <div key={k} className="rounded-md border border-line px-3 py-2">
                <dd className="font-mono text-[17px] font-semibold tabular-nums">{v ?? "–"}</dd>
                <dt className="text-[11px] leading-tight text-ink-3">{k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, " ")}</dt>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </Card>
  );
}

/* ---------------------------------------------------------------------------------------------------------
 * Tiers, scoring, models, guarantees */

function Tiers({ tiers }: { tiers: Data["tiers"] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Card className="h-full">
      <CardHeader icon={Layers} title="Priority tiers" subtitle="Lower tiers always win. Only teachers' rules (Tiers 3–4) can be offered for waiving; Tiers 0–2 go to the office" />
      <div className="space-y-1.5 p-5">
        {tiers.map((t, i) => {
          const tone = (TIER[t.tier] ?? TIER[5]).tone;
          const mode = t.relaxable_in_negotiation ? "negotiable" : t.tier === 5 ? "preference" : "escalate only";
          return (
            <motion.button
              key={t.tier}
              onClick={() => setOpen(open === t.tier ? null : t.tier)}
              initial={{ scaleX: 0.3, opacity: 0 }}
              whileInView={{ scaleX: 1, opacity: 1 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.08, type: "spring", stiffness: 200, damping: 24 }}
              style={{ width: `${100 - i * 7}%`, originX: 0 }}
              className={clsx("block rounded-md border-l-4 bg-panel-2/60 px-3 py-2 text-left hover:bg-panel-2", HUE[tone].border)}
            >
              <span className="flex items-center gap-2 text-[13px]">
                <span className={clsx("font-mono text-[11px]", HUE[tone].text)}>T{t.tier}</span>
                <span className="font-medium">{(TIER[t.tier] ?? TIER[5]).name}</span>
                <span className="ml-auto flex items-center gap-1 text-[11px] text-ink-3">
                  {mode === "escalate only" ? <Lock size={11} /> : mode === "negotiable" ? <Users size={11} /> : <Scale size={11} />}
                  {mode}
                </span>
              </span>
              <AnimatePresence initial={false}>
                {open === t.tier && (
                  <motion.span
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="block overflow-hidden text-[12px] text-ink-2"
                  >
                    <span className="mt-1.5 block">Relaxed by: {t.who}</span>
                    <span className="block text-ink-3">e.g. {t.examples}</span>
                  </motion.span>
                )}
              </AnimatePresence>
            </motion.button>
          );
        })}
        <p className="pt-1 text-[11.5px] text-ink-3">Click a tier for who may relax it and examples.</p>
      </div>
    </Card>
  );
}

function Bar({ value, tone = "brand", delay = 0 }: { value: number; tone?: keyof typeof HUE; delay?: number }) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-panel-2">
      <motion.div
        className={clsx("h-full rounded-full", HUE[tone].dot)}
        initial={{ width: 0 }}
        whileInView={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
        viewport={{ once: true }}
        transition={{ delay, duration: 0.7, ease: "easeOut" }}
      />
    </div>
  );
}

/** The agent's tool scopes, in the order a request goes through them. */
const SCOPES: [string, string, keyof typeof HUE][] = [
  ["read", "Read the department", "info"],
  ["policy", "Read the rules", "info"],
  ["draft", "Draft a change", "brand"],
  ["rearrange", "Rearrange classes", "brand"],
  ["extend", "Cancel, add, limit, book", "brand"],
  ["compose", "Combine and relate", "brand"],
  ["evaluate", "Check with the solver", "ok"],
  ["talk", "Ask people", "warn"],
  ["end", "Submit, decline, escalate", "violet"],
];

function Tools({ tools }: { tools: Record<string, string[]> }) {
  const most = Math.max(1, ...Object.values(tools).map((t) => t.length));
  return (
    <Card className="h-full">
      <CardHeader icon={Workflow} title="What the agent can do" subtitle="Typed tools, by scope: the agent acts only through these, and each checks who may do what" />
      <div className="space-y-3 p-5">
        {SCOPES.filter(([k]) => tools[k]?.length).map(([k, label, tone], i) => (
          <div key={k} className="grid grid-cols-[150px_minmax(0,1fr)] items-start gap-3 text-[13px]">
            <div>
              <p className="font-medium">{label}</p>
              <div className="mt-1 w-24">
                <Bar value={tools[k].length / most} tone={tone} delay={i * 0.06} />
              </div>
            </div>
            <div className="flex flex-wrap gap-1">
              {tools[k].map((t) => (
                <span key={t} className="rounded bg-panel-2 px-1.5 py-0.5 font-mono text-[11px] text-ink-2">
                  {t}
                </span>
              ))}
            </div>
          </div>
        ))}
        <p className="text-[12px] text-ink-3">A question is offered only the reading tools; a change gets them all.</p>
      </div>
    </Card>
  );
}

function AgentModel({ agent, systemOne }: { agent: Data["agent"]; systemOne: Data["system_one"] }) {
  const b = agent.budgets;
  return (
    <Card className="h-full">
      <CardHeader icon={Brain} title="The agent's model" subtitle="The model proposes tool calls; the tools, the solver and the commit gate decide" />
      <div className="p-5">
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="inline-block rounded-lg border border-brand/50 bg-brand/8 px-4 py-2"
        >
          <p className="text-[11px] text-brand">{agent.adapter ? "fine-tuned adapter" : "model"}</p>
          <p className="font-mono text-[13px] font-semibold">{agent.adapter ?? agent.model}</p>
          {agent.adapter && <p className="font-mono text-[11px] text-ink-3">on {agent.model}</p>}
        </motion.div>
        <ul className="mt-3 space-y-1.5 text-[13px]">
          <li className="flex items-center gap-3">
            <span className="w-40 shrink-0 font-medium">Agent</span>
            <span className="rounded bg-panel-2 px-2 py-0.5 font-mono text-[11.5px] text-ink-2">{agent.config}</span>
          </li>
          <li className="flex items-center gap-3">
            <span className="w-40 shrink-0 font-medium">Tool picker</span>
            <span className="text-ink-2">{agent.picker ? "System One (linear SVM): questions get the reading tools" : "off: every message gets every tool"}</span>
          </li>
          <li className="flex items-center gap-3">
            <span className="w-40 shrink-0 font-medium">Solver</span>
            <span className="text-ink-2">CP-SAT repair, the kernel's validator at the commit gate</span>
          </li>
          {agent.url && (
            <li className="flex items-center gap-3">
              <span className="w-40 shrink-0 font-medium">Served at</span>
              <span className="min-w-0 truncate font-mono text-[11.5px] text-ink-3" title={agent.url}>
                {agent.url}
              </span>
            </li>
          )}
        </ul>
        <div className="mt-4 grid grid-cols-2 gap-2 border-t border-line pt-4 text-[12px] sm:grid-cols-4">
          <Fact k="Context" v={b.context_tokens ? `${b.context_tokens.toLocaleString()} tokens` : "–"} />
          <Fact k="Calls per turn" v={String(b.max_calls_per_turn ?? "–")} />
          <Fact k="Episodes so far" v={`${agent.episodes} (${agent.requests} requests)`} />
          <Fact k="System One" v={`${systemOne.trained_on ?? "–"} examples`} />
        </div>
      </div>
    </Card>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div className="min-w-0">
      <p className="text-ink-3">{k}</p>
      <p className="truncate font-medium" title={v}>
        {v}
      </p>
    </div>
  );
}

const SAFETY_ICON: LucideIcon[] = [CalendarCheck, Lock, CircleSlash, Eye, ShieldCheck, MessageSquareText, Layers];

function Safety({ items }: { items: string[] }) {
  return (
    <Card className="h-full">
      <CardHeader icon={ShieldCheck} title="Safety guarantees" subtitle="Enforced by code, not by any model" />
      <ul className="grid gap-2 p-5 sm:grid-cols-2">
        {items.map((s, i) => {
          const Icon = SAFETY_ICON[i] ?? Lock;
          return (
            <motion.li
              key={s}
              initial={{ opacity: 0, scale: 0.95 }}
              whileInView={{ opacity: 1, scale: 1 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.06 }}
              className="flex gap-2.5 rounded-md border border-line p-3 text-[12.5px] leading-relaxed"
            >
              <span className="grid size-7 shrink-0 place-items-center rounded-md bg-ok/12 text-ok">
                <Icon size={14} />
              </span>
              {s}
            </motion.li>
          );
        })}
      </ul>
    </Card>
  );
}
