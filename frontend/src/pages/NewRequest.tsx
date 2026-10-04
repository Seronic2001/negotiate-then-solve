import { ArrowRight, Eraser, Send, Undo2 } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Lifecycle } from "../components/Lifecycle";
import { MyClasses } from "../components/MyClasses";
import { Button, Card, Kbd, Label, LiveDot, PageHeader, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { mentionInto, mentions, removeMention } from "../lib/mention";

export default function NewRequest() {
  const { user } = useAuth();
  const [text, setText] = useState("");
  const [history, setHistory] = useState<string[]>([]); // the text before each click-made change, for Undo
  const box = useRef<HTMLTextAreaElement>(null);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const { data: inst } = useApi(() => api.instance(), []);
  const { data: detail } = useApi(() => (caseId ? api.case(caseId) : Promise.resolve(null)), [caseId], caseId ? 900 : undefined);

  const examples = useMemo(() => {
    if (!user || !inst) return [];
    const practical = inst.sessions.find((s) => s.faculty === user.id && s.kind === "practical");
    if (user.role === "student") return ["Machine Learning and Algorithms clash on Tuesday at 10 am for 12 of us. Can this be looked at?", "Please cancel Dr. Khan's Friday lecture, we have a quiz."];
    if (user.role === "lab_incharge") return ["Lab 1 is closed for maintenance in weeks 11-12.", "Lab 2 will be unavailable in week 6 while the wiring is replaced."];
    if (user.role === "coordinator") return ["Who has to approve moving a class outside regular hours?"];
    return [
      "I'm at a conference in week 10, Wednesday and Thursday, so I can't take my classes then.",
      "I'd prefer no classes before 11 am on Friday, if possible.",
      practical ? `My ${practical.title} practical needs the routers; it has to be on Wednesday afternoon.` : "Please keep my Friday afternoons free.",
      "Could you schedule my lecture at 1 pm on Thursday? It's the only time that works.",
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

  /** A change made by a click (a class, an example, Clear): remembered so Undo can take it back. */
  const edit = (next: string) => {
    setHistory((h) => [...h.slice(-49), text]);
    setText(next);
  };
  const undo = () => {
    if (!history.length) return;
    setText(history[history.length - 1]);
    setHistory((h) => h.slice(0, -1));
    box.current?.focus();
  };
  /** A class picked from the list goes into the text at the cursor, once; picking it again takes it out. */
  const mention = (phrase: string) => (mentions(text, phrase) ? edit(removeMention(text, phrase)) : mentionInto(box.current, text, phrase, edit));

  return (
    <div className="grid max-w-5xl gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0">
        <PageHeader title="New request" subtitle="Write it the way you would write an email to the timetable office." />

        {!caseId ? (
          <>
            <Card className="p-4 transition-colors focus-within:border-brand/60">
              <textarea
                ref={box}
                autoFocus
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void send();
                }}
                rows={6}
                placeholder="e.g. I'm at a conference in week 7, Tuesday to Thursday."
                className="w-full resize-none bg-transparent text-[15px] leading-relaxed outline-none placeholder:text-ink-3 focus-visible:outline-none"
              />
              <div className="mt-2 flex items-center justify-between border-t border-line pt-3">
                <p className="flex items-center gap-1 text-[12px] text-ink-3">
                  <Kbd>Ctrl</Kbd>+<Kbd>Enter</Kbd> to send
                </p>
                <div className="flex items-center gap-1.5">
                  <Button variant="ghost" size="sm" icon={Undo2} onClick={undo} disabled={!history.length} title="Undo the last class, example or clear">
                    Undo
                  </Button>
                  <Button variant="ghost" size="sm" icon={Eraser} onClick={() => edit("")} disabled={!text} title="Clear the text (Undo brings it back)">
                    Clear
                  </Button>
                  <Button variant="primary" icon={Send} loading={sending} onClick={send} disabled={!text.trim()}>
                    Send
                  </Button>
                </div>
              </div>
              {error && <p className="mt-3 text-[13px] text-bad">{error}</p>}
            </Card>

            {examples.length > 0 && (
              <div className="mt-6">
                <Label>Examples</Label>
                <ul className="space-y-1">
                  {examples.map((ex) => (
                    <li key={ex}>
                      <button onClick={() => edit(ex)} className="text-left text-[13.5px] text-ink-2 hover:text-brand">
                        “{ex}”
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <Card className="p-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <p className="text-[14.5px] leading-relaxed">“{detail?.text ?? text}”</p>
              {detail && <StatusBadge status={detail.status} live={detail.running} />}
            </div>
            <Lifecycle events={detail?.events ?? []} status={detail?.status ?? "received"} live={detail?.running ?? true} />

            {detail?.status === "negotiating" && (
              <p className="mt-5 flex items-center gap-2 text-[13.5px] text-ink-2">
                <LiveDot tone="warn" /> This clashes with someone else's timetable. They have been sent options that work and we are waiting for their reply.
              </p>
            )}
            {detail?.reply && !detail.running && (
              <div className="mt-5 border-l-2 border-brand pl-4">
                <Label>Reply</Label>
                <p className="text-[14.5px] leading-relaxed">{detail.reply}</p>
              </div>
            )}

            <div className="mt-6 flex flex-wrap gap-2 border-t border-line pt-4">
              <Link to={`/requests/${caseId}`}>
                <Button icon={ArrowRight}>Open request</Button>
              </Link>
              <Button
                variant="ghost"
                onClick={() => {
                  setCaseId(null);
                  setText("");
                  setHistory([]);
                }}
              >
                Write another
              </Button>
            </div>
          </Card>
        )}
      </div>
      <aside className="lg:pt-[72px]">
        <MyClasses onPick={caseId ? undefined : mention} text={text} />
      </aside>
    </div>
  );
}
