import clsx from "clsx";
import { RotateCcw } from "lucide-react";
import { useState } from "react";
import { Button } from "./ui";

/** 1-5 ratings of a message, as the study and the judge use them (clarity, acceptability). */
export function Likert({ label, low, high, value, onChange }: { label: string; low: string; high: string; value: number | null; onChange: (v: number) => void }) {
  return (
    <div>
      <p className="text-[14px] font-medium">{label}</p>
      <div className="mt-2.5 max-w-md">
        <div role="radiogroup" aria-label={label} className="grid grid-cols-5 overflow-hidden rounded-md border border-line">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              role="radio"
              aria-checked={value === n}
              onClick={() => onChange(n)}
              className={clsx(
                "h-10 text-[14px] font-medium transition-colors",
                n > 1 && "border-l border-line",
                value === n ? "bg-brand text-panel" : "bg-panel text-ink-2 hover:bg-panel-2",
              )}
            >
              {n}
            </button>
          ))}
        </div>
        <div className="mt-1.5 flex justify-between text-[12px] text-ink-3">
          <span>1 · {low}</span>
          <span>{high} · 5</span>
        </div>
      </div>
    </div>
  );
}

export function RatingForm({ busy, onSave, submitLabel = "Save and next" }: { busy: boolean; onSave: (v: Record<string, unknown>) => void; submitLabel?: string }) {
  const [clarity, setClarity] = useState<number | null>(null);
  const [acceptability, setAcceptability] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  return (
    <div className="space-y-5">
      <Likert label="How clear is what happened, and what you are asked to do?" low="confusing" high="immediately clear" value={clarity} onChange={setClarity} />
      <Likert label="How acceptable would this message be to receive?" low="unreasonable" high="fair, easy to agree to" value={acceptability} onChange={setAcceptability} />
      <textarea
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        rows={2}
        placeholder="Anything that stood out? (optional)"
        className="w-full max-w-md resize-none rounded-md border border-line bg-panel px-3 py-2 text-[13.5px] outline-none focus:border-brand/60"
      />
      <div className="flex items-center gap-2">
        <Button variant="primary" disabled={busy || !clarity || !acceptability} loading={busy} onClick={() => onSave({ clarity, acceptability, ...(comment.trim() ? { comment: comment.trim() } : {}) })}>
          {submitLabel}
        </Button>
        <Button
          variant="ghost"
          icon={RotateCcw}
          disabled={busy || (!clarity && !acceptability && !comment)}
          onClick={() => {
            setClarity(null);
            setAcceptability(null);
            setComment("");
          }}
        >
          Clear
        </Button>
      </div>
    </div>
  );
}
