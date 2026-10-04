import clsx from "clsx";
import { useState } from "react";
import { Button } from "./ui";

/** 1-5 ratings of a message, as the study and the judge use them (clarity, acceptability). */
export function Likert({ label, low, high, value, onChange }: { label: string; low: string; high: string; value: number | null; onChange: (v: number) => void }) {
  return (
    <div>
      <p className="text-[13.5px] font-medium">{label}</p>
      <div className="mt-2 flex items-center gap-2">
        <span className="hidden w-28 text-right text-[12px] text-ink-3 sm:block">{low}</span>
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            onClick={() => onChange(n)}
            className={clsx("grid size-9 place-items-center rounded-md border text-[14px] font-medium", value === n ? "border-brand bg-brand text-panel" : "border-line bg-panel text-ink-2 hover:border-brand/50")}
          >
            {n}
          </button>
        ))}
        <span className="hidden w-28 text-[12px] text-ink-3 sm:block">{high}</span>
      </div>
      <p className="mt-1 text-[11.5px] text-ink-3 sm:hidden">
        1 = {low}, 5 = {high}
      </p>
    </div>
  );
}

export function RatingForm({ busy, onSave, submitLabel = "Save and next" }: { busy: boolean; onSave: (v: Record<string, unknown>) => void; submitLabel?: string }) {
  const [clarity, setClarity] = useState<number | null>(null);
  const [acceptability, setAcceptability] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  return (
    <div className="space-y-4">
      <Likert label="How clear is it what happened and what you are asked to do?" low="confusing" high="immediately clear" value={clarity} onChange={setClarity} />
      <Likert label="How acceptable would this message be to receive?" low="unreasonable" high="fair and easy to agree to" value={acceptability} onChange={setAcceptability} />
      <input
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="Comment (optional)"
        className="w-full rounded-md border border-line bg-panel px-3 py-2 text-[13.5px] outline-none focus:border-brand/60"
      />
      <Button variant="primary" disabled={busy || !clarity || !acceptability} loading={busy} onClick={() => onSave({ clarity, acceptability, ...(comment.trim() ? { comment: comment.trim() } : {}) })}>
        {submitLabel}
      </Button>
    </div>
  );
}

