import { HelpCircle, Send } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { mentionInto } from "../lib/mention";
import { WeekCalendar } from "./WeekCalendar";
import { Button } from "./ui";

/** The sender answers the question their request was sent back with; the request then goes through
 * the pipeline again, read together with the answer. Shown only to the sender. */
export function ClarifyForm({ caseId, sender, question, calendar = true, onSent }: {
  caseId: string;
  sender: string;
  question: string;
  calendar?: boolean;
  onSent?: () => void;
}) {
  const { user } = useAuth();
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  if (user?.id !== sender) return null;
  const send = async () => {
    setSending(true);
    setError(null);
    try {
      await api.clarify(caseId, text.trim());
      setText("");
      onSent?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  };
  return (
    <div className="mt-4 rounded-lg border border-brand/40 bg-brand/5 p-3">
      <p className="flex items-start gap-2 text-[13.5px]">
        <HelpCircle size={15} className="mt-0.5 shrink-0 text-brand" /> {question}
      </p>
      <textarea
        ref={box}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && (e.ctrlKey || e.metaKey) && text.trim() && void send()}
        rows={2}
        placeholder="e.g. Wednesday and Thursday in week 10"
        className="mt-2 w-full resize-none rounded-md border border-line bg-panel px-3 py-2 text-[14px] outline-none focus:border-brand/60"
      />
      <div className="mt-2 flex items-center justify-between gap-2">
        <Link to={`/requests/${caseId}`} className="text-[12px] text-ink-3 hover:text-brand">
          {caseId}
        </Link>
        <Button variant="primary" size="sm" icon={Send} loading={sending} disabled={!text.trim()} onClick={send}>
          Send answer
        </Button>
      </div>
      {error && <p className="mt-2 text-[12.5px] text-bad">{error}</p>}
      {calendar && <WeekCalendar text={text} onPick={(p) => mentionInto(box.current, text, p, setText)} onRemove={setText} />}
    </div>
  );
}
