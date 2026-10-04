import { ArrowLeft, ArrowRight, Check, ClipboardCheck, LogOut, MessageSquareText, Play, Star, X } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { RatingForm } from "../components/Rating";
import { Button, Card, CardHeader, Label, Mark, Meter, Skeleton } from "../components/ui";
import { useAuth } from "../lib/auth";
import { setStudyCode, setStudyTask, study, studyCode, type NextItem, type StudySession, type StudyTask } from "../lib/study";

const TASK: Record<StudyTask, { title: string; text: string; icon: typeof Star }> = {
  ratings: {
    title: "Rate messages",
    text: "Messages the timetable office sent to faculty about a clash. Rate how clear each is, and how acceptable it would be to receive.",
    icon: Star,
  },
  claims: {
    title: "Check claims",
    text: "One sentence from an explanation, and the facts it was allowed to use. Is everything it states backed by those facts?",
    icon: ClipboardCheck,
  },
  replies: {
    title: "Label replies",
    text: "A faculty member's reply to a message. What does the reply do?",
    icon: MessageSquareText,
  },
};

export default function Study() {
  const [session, setSession] = useState<StudySession | null>(null);
  const [loading, setLoading] = useState(!!studyCode());
  const [task, setTask] = useState<StudyTask | null>(null);

  const refresh = useCallback(async () => {
    if (!studyCode()) return;
    try {
      setSession(await study.me());
    } catch {
      setStudyCode(null);
      setSession(null);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => void refresh(), [refresh]);

  const leave = () => {
    setStudyCode(null);
    setStudyTask(null);
    setSession(null);
    setTask(null);
  };

  return (
    <div className="min-h-full bg-bg">
      <header className="flex h-14 items-center gap-2.5 border-b border-line bg-panel px-4 sm:px-8">
        <Mark size={22} />
        <span className="font-serif text-[15px] font-semibold">Timetable study</span>
        {session && (
          <span className="ml-auto flex items-center gap-3 text-[13px] text-ink-3">
            <span className="font-mono">{session.code}</span>
            <button onClick={leave} className="flex items-center gap-1.5 hover:text-ink" title="Leave this device (your answers are kept)">
              <LogOut size={14} /> Leave
            </button>
          </span>
        )}
      </header>
      <main className="mx-auto max-w-3xl px-4 py-8 sm:px-8">
        {loading ? (
          <Skeleton className="h-64" />
        ) : !session ? (
          <CodeEntry onIn={setSession} />
        ) : !session.consented ? (
          <Consent session={session} onDone={setSession} />
        ) : task ? (
          <Labeler task={session.kind === "pilot" && task !== "ratings" ? "ratings" : task} session={session} onBack={() => { setTask(null); void refresh(); }} />
        ) : (
          <Home session={session} onTask={setTask} />
        )}
      </main>
    </div>
  );
}

function CodeEntry({ onIn }: { onIn: (s: StudySession) => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      const s = await study.me(code.trim().toUpperCase());
      setStudyCode(s.code);
      onIn(s);
    } catch {
      setError("That code is not known. Check it with the person running the study.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card className="mx-auto max-w-md p-6">
      <h1 className="font-serif text-[22px] font-semibold">Take part</h1>
      <p className="mt-1 text-[13.5px] text-ink-3">Enter the participant code you were given. It is the only thing that identifies your answers.</p>
      <input
        value={code}
        onChange={(e) => setCode(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && code.trim() && void go()}
        placeholder="e.g. P-03"
        className="mt-5 w-full rounded-md border border-line bg-panel px-3 py-2 font-mono text-[15px] uppercase outline-none focus:border-brand/60"
        autoFocus
      />
      {error && <p className="mt-2 text-[13px] text-bad">{error}</p>}
      <Button variant="primary" className="mt-4 w-full" disabled={!code.trim()} loading={busy} onClick={go} icon={ArrowRight}>
        Continue
      </Button>
    </Card>
  );
}

function Consent({ session, onDone }: { session: StudySession; onDone: (s: StudySession) => void }) {
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <Card>
      <CardHeader title="Before you start" subtitle={`Participant ${session.code}`} />
      <div className="space-y-4 p-5 text-[14px] leading-relaxed">
        <p>
          {session.kind === "pilot"
            ? "This study looks at how a timetabling assistant writes to faculty when a request clashes with someone else's. You will rate some messages it wrote, then try it yourself in a short practice session, about 20 minutes in all."
            : "Team labelling for judge validation: you will rate messages, check explanation claims against their facts, and label replies."}
        </p>
        <ul className="list-disc space-y-1.5 pl-5 text-ink-2">
          {session.consent_text.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
        <label className="flex items-start gap-2.5 rounded-md border border-line bg-panel-2 p-3">
          <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} className="mt-1" />
          <span>I have read this and agree to take part.</span>
        </label>
        <Button
          variant="primary"
          disabled={!agree}
          loading={busy}
          onClick={async () => {
            setBusy(true);
            onDone(await study.consent());
          }}
        >
          Start
        </Button>
      </div>
    </Card>
  );
}

function Home({ session, onTask }: { session: StudySession; onTask: (t: StudyTask) => void }) {
  if (!session.items_ready)
    return (
      <Card className="p-6 text-[14px] text-ink-2">
        The study material is not ready yet. The coordinator builds it with <code className="font-mono">uv run python -m evaluation.study build</code>.
      </Card>
    );
  return (
    <div className="space-y-5">
      <div>
        <h1 className="font-serif text-[24px] font-semibold">{session.kind === "pilot" ? "Thank you for taking part" : "Labelling tasks"}</h1>
        <p className="mt-1 text-[13.5px] text-ink-3">
          {session.kind === "pilot" ? "Two parts: rate some messages, then try the system yourself. Either order works." : "Do them in any order; your answers are saved as you go."}
        </p>
      </div>
      {session.tasks.map((t) => {
        const p = session.progress[t];
        const Icon = TASK[t].icon;
        const done = p && p.done >= p.total;
        return (
          <Card key={t} className="p-5">
            <div className="flex items-start gap-4">
              <Icon size={18} className="mt-0.5 shrink-0 text-ink-3" />
              <div className="min-w-0 flex-1">
                <p className="text-[14.5px] font-semibold">{TASK[t].title}</p>
                <p className="mt-0.5 text-[13.5px] text-ink-3">{TASK[t].text}</p>
                {p && (
                  <div className="mt-3 flex items-center gap-3">
                    <Meter value={p.done} max={p.total || 1} tone={done ? "ok" : "brand"} className="max-w-56 flex-1" />
                    <span className="font-mono text-[12px] text-ink-3">
                      {p.done}/{p.total}
                    </span>
                  </div>
                )}
              </div>
              <Button variant={done ? "secondary" : "primary"} onClick={() => onTask(t)} disabled={done} icon={done ? Check : ArrowRight}>
                {done ? "Done" : p?.done ? "Continue" : "Start"}
              </Button>
            </div>
          </Card>
        );
      })}
      {session.kind === "pilot" && session.persona && <LiveSession session={session} />}
    </div>
  );
}

function LiveSession({ session }: { session: StudySession }) {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (what: "preference" | "practice") => {
    setBusy(what);
    setError(null);
    try {
      await signIn(session.persona!);
      if (what === "practice") {
        const p = await study.practice();
        setStudyTask(p.task);
        navigate("/new");
      } else {
        setStudyTask("Tell the timetable office one teaching preference of your own (for example, times you would rather not teach), in your own words.");
        navigate("/new");
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card className="p-5">
      <div className="flex items-start gap-4">
        <Play size={18} className="mt-0.5 shrink-0 text-ink-3" />
        <div className="min-w-0 flex-1">
          <p className="text-[14.5px] font-semibold">Try it yourself</p>
          <p className="mt-0.5 text-[13.5px] text-ink-3">
            You use the real portal as <span className="font-medium text-ink-2">{session.persona_name}</span>, a demo faculty member. Write in your own words: the system reads what you type.
          </p>
          <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-[13.5px] text-ink-2">
            <li>Send a preference. Afterwards, say whether the system understood it.</li>
            <li>The practice clash: a colleague has claimed a lab you need. Ask for it, then answer the office's message in your own words and confirm how it read your reply.</li>
            <li>Rate the message you received (a box appears under it).</li>
          </ol>
          {error && <p className="mt-3 text-[13px] text-bad">{error}</p>}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button onClick={() => run("preference")} loading={busy === "preference"}>
              1 · Send a preference
            </Button>
            <Button variant="primary" onClick={() => run("practice")} loading={busy === "practice"}>
              2 · Start the practice clash
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}

function Labeler({ task, session, onBack }: { task: StudyTask; session: StudySession; onBack: () => void }) {
  const [next, setNext] = useState<NextItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => setNext(await study.next(task)), [task]);
  useEffect(() => void load(), [load]);

  const save = async (value: Record<string, unknown>) => {
    if (!next?.item) return;
    setBusy(true);
    setError(null);
    try {
      await study.label(task, next.item.id, value);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <button onClick={onBack} className="inline-flex items-center gap-1.5 text-[13px] text-ink-3 hover:text-ink">
        <ArrowLeft size={14} /> All tasks
      </button>
      <div className="flex items-center gap-3">
        <h1 className="font-serif text-[22px] font-semibold">{TASK[task].title}</h1>
        {next && (
          <span className="ml-auto font-mono text-[12px] text-ink-3">
            {Math.min(next.done + 1, next.total)} of {next.total}
          </span>
        )}
      </div>
      {next && <Meter value={next.done} max={next.total || 1} />}
      <p className="text-[13.5px] text-ink-3">{TASK[task].text}</p>
      {!next ? (
        <Skeleton className="h-64" />
      ) : !next.item ? (
        <Card className="p-8 text-center">
          <Check size={22} className="mx-auto text-ok" />
          <p className="mt-2 text-[15px] font-medium">All done. Thank you!</p>
          <Button className="mt-4" onClick={onBack}>
            Back to the tasks
          </Button>
        </Card>
      ) : "claim" in next.item ? (
        <ClaimItem key={next.item.id} item={next.item} busy={busy} onSave={save} />
      ) : "reply" in next.item ? (
        <ReplyItem key={next.item.id} item={next.item} labels={session.reply_labels} busy={busy} onSave={save} />
      ) : (
        <RatingItem key={next.item.id} text={next.item.text} busy={busy} onSave={save} />
      )}
      {error && <p className="rounded-md bg-bad/10 px-3 py-2 text-sm text-bad">{error}</p>}
    </div>
  );
}

function Quote({ children }: { children: ReactNode }) {
  return <div className="whitespace-pre-line rounded-md border border-line bg-panel-2 p-4 text-[14px] leading-relaxed">{children}</div>;
}

function ClaimItem({ item, busy, onSave }: { item: { claim: string; facts: { id: string; text: string }[] }; busy: boolean; onSave: (v: Record<string, unknown>) => void }) {
  return (
    <Card>
      <div className="space-y-4 p-5">
        <div>
          <Label>The facts</Label>
          <ul className="space-y-1.5 text-[13px] text-ink-2">
            {item.facts.map((f) => (
              <li key={f.id} className="flex gap-2">
                <span className="shrink-0 font-mono text-[11.5px] text-ink-3">{f.id}</span>
                <span>{f.text}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <Label>The claim</Label>
          <Quote>{item.claim}</Quote>
        </div>
        <p className="text-[12.5px] text-ink-3">Supported means every day, time, room, name and number in the claim appears in the facts, and nothing in it contradicts them.</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="success" icon={Check} disabled={busy} onClick={() => onSave({ supported: true })}>
            Supported
          </Button>
          <Button variant="danger" icon={X} disabled={busy} onClick={() => onSave({ supported: false })}>
            Not supported
          </Button>
        </div>
      </div>
    </Card>
  );
}

const REPLY_TEXT: Record<string, string> = {
  counter: "Suggests other days or times",
  reject: "Declines, without another time",
  other: "Something else (a question, unclear)",
};

function ReplyItem({ item, labels, busy, onSave }: { item: { message: string; reply: string }; labels: string[]; busy: boolean; onSave: (v: Record<string, unknown>) => void }) {
  const letters = new Set([...item.message.matchAll(/^([A-Z])\) /gm)].map((m) => m[1]));
  const shown = labels.filter((l) => !l.startsWith("accept:") || letters.has(l.slice(7)));
  return (
    <Card>
      <div className="space-y-4 p-5">
        <div>
          <Label>The office's message</Label>
          <Quote>{item.message}</Quote>
        </div>
        <div>
          <Label>The reply</Label>
          <Quote>{item.reply}</Quote>
        </div>
        <div className="flex flex-wrap gap-2">
          {shown.map((l) => (
            <Button key={l} variant={l.startsWith("accept:") ? "primary" : "secondary"} disabled={busy} onClick={() => onSave({ label: l })}>
              {l.startsWith("accept:") ? `Accepts option ${l.slice(7)}` : REPLY_TEXT[l] ?? l}
            </Button>
          ))}
        </div>
      </div>
    </Card>
  );
}

function RatingItem({ text, busy, onSave }: { text: string; busy: boolean; onSave: (v: Record<string, unknown>) => void }) {
  return (
    <Card>
      <div className="space-y-5 p-5">
        <div>
          <Label>Imagine you received this message</Label>
          <Quote>{text}</Quote>
        </div>
        <RatingForm busy={busy} onSave={onSave} />
      </div>
    </Card>
  );
}
