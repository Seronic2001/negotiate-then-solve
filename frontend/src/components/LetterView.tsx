import { Mark } from "./ui";

/** A negotiation message as its recipient sees it: the prose, then the options as cards.
 * Takes the message text as sent ("...\n\nOptions:\nA) ...\nReply with a letter..."). */

export type Placement = { session: string; course: string; day: string; time: string; room: string };

/** "the Compiler Design practical (C3-P) on Friday at 3 pm in Lab 1" */
export function parsePlacement(text: string): Placement | null {
  const x = text.trim().match(/^(?:the )?(.+?) \(([^)]+)\) on (\w+) at (.+?) in (.+?)\.?$/);
  return x ? { course: x[1], session: x[2], day: x[3], time: x[4], room: x[5] } : null;
}

export function parseMessage(text: string) {
  const [prose, rest = ""] = text.split(/\n\s*\nOptions:\s*\n/);
  const options: { key: string; text: string; placements: Placement[] | null }[] = [];
  const footer: string[] = [];
  for (const line of rest.split("\n").map((l) => l.trim()).filter(Boolean)) {
    const m = line.match(/^([A-Z])\)\s*(.+)$/);
    if (m) {
      const ps = m[2].split("; ").map(parsePlacement);
      options.push({ key: m[1], text: m[2], placements: ps.every(Boolean) ? (ps as Placement[]) : null });
    } else footer.push(line);
  }
  return { paragraphs: prose.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean), options, footer };
}

export function LetterView({ text }: { text: string }) {
  const { paragraphs, options, footer } = parseMessage(text);
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-panel shadow-sm">
      <div className="flex items-center gap-2.5 border-b border-line bg-panel-2/60 px-4 py-2.5">
        <span className="grid size-7 place-items-center rounded-full border border-line bg-panel">
          <Mark size={15} />
        </span>
        <div className="min-w-0 leading-tight">
          <p className="text-[13px] font-semibold">Timetable office</p>
          <p className="text-[11.5px] text-ink-3">to you · about a clash in your timetable</p>
        </div>
      </div>
      <div className="space-y-3 px-5 py-4 text-[14.5px] leading-relaxed">
        {paragraphs.map((p) => (
          <p key={p} className="whitespace-pre-line">
            {p}
          </p>
        ))}
      </div>
      {options.length > 0 && (
        <div className="border-t border-line bg-panel-2/40 px-5 py-4">
          <p className="mb-2.5 text-[11.5px] font-medium tracking-wide text-ink-3 uppercase">Your options</p>
          <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {options.map((o) => (
              <div key={o.key} className="flex gap-3 rounded-md border border-line bg-panel p-3">
                <span className="grid size-7 shrink-0 place-items-center rounded-full bg-brand/10 text-[13px] font-semibold text-brand">{o.key}</span>
                <div className="min-w-0 space-y-1.5">
                  {o.placements ? (
                    o.placements.map((p) => (
                      <div key={p.session} className="leading-tight">
                        <p className="text-[14px] font-semibold">
                          {p.day}, {p.time}
                        </p>
                        <p className="text-[12.5px] text-ink-2">{p.room}</p>
                        <p className="truncate text-[11.5px] text-ink-3" title={`${p.course} (${p.session})`}>
                          {p.course} · {p.session}
                        </p>
                      </div>
                    ))
                  ) : (
                    <p className="text-[13px]">{o.text}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
          {footer.length > 0 && <p className="mt-3 text-[12.5px] text-ink-3">{footer.join(" ")}</p>}
        </div>
      )}
      {!options.length && footer.length > 0 && <p className="border-t border-line px-5 py-3 text-[12.5px] text-ink-3">{footer.join(" ")}</p>}
    </div>
  );
}
