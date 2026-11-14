import clsx from "clsx";
import type { ReactNode } from "react";
import { ReplyText } from "./ReplyText";

/** The agent's answer, laid out to be read at a glance. The model is asked for plain sentences but a small model
 * often writes Markdown anyway, so both are handled: headings, bullet and numbered lists, **bold**, *italics* and
 * `code` are drawn as such (never shown as raw symbols); a plain paragraph of the form "Lead: item; item." goes to
 * ReplyText, which lays it out as a list. In running text, times ("Tuesday 2–3 pm") are set in medium weight and
 * rooms ("Room 104", "Lab 1") as small tags, so the facts an answer is about stand out. */
export function AgentText({ text, className }: { text: string; className?: string }) {
  const blocks = parse(text);
  return (
    <div className={clsx("space-y-2 leading-relaxed", className)}>
      {blocks.map((b, i) => (
        <Block key={i} b={b} />
      ))}
    </div>
  );
}

type Blk =
  | { t: "h"; text: string }
  | { t: "ul"; items: string[] }
  | { t: "ol"; items: string[] }
  | { t: "p"; text: string };

const BULLET = /^\s*(?:[-*•])\s+(.*)$/;
const NUMBER = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s*#{1,6}\s+(.*)$/;

function parse(text: string): Blk[] {
  const out: Blk[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) out.push({ t: "p", text: para.join(" ") });
    para = [];
  };
  for (const raw of text.replace(/\r/g, "").split("\n")) {
    const line = raw.trimEnd();
    let m: RegExpExecArray | null;
    if (!line.trim()) flush();
    else if ((m = HEADING.exec(line))) {
      flush();
      out.push({ t: "h", text: m[1] });
    } else if ((m = BULLET.exec(line)) || (m = NUMBER.exec(line))) {
      flush();
      const kind = BULLET.test(line) ? "ul" : "ol";
      const last = out[out.length - 1];
      if (last && last.t === kind) last.items.push(m[1]);
      else out.push({ t: kind, items: [m[1]] });
    } else if (/^\s{2,}\S/.test(raw) && out.length && (out[out.length - 1].t === "ul" || out[out.length - 1].t === "ol") && !para.length) {
      const last = out[out.length - 1] as { items: string[] }; // an indented line continues the item above
      last.items[last.items.length - 1] += " " + line.trim();
    } else para.push(line.trim());
  }
  flush();
  return out;
}

function Block({ b }: { b: Blk }) {
  if (b.t === "h") return <p className="pt-1 text-[12.5px] font-semibold uppercase tracking-wide text-ink-2">{inline(b.text)}</p>;
  if (b.t === "ul")
    return (
      <ul className="space-y-1">
        {b.items.map((it, i) => (
          <li key={i} className="flex gap-2">
            <span className="mt-[9px] size-1.5 shrink-0 rounded-full bg-brand/60" />
            <span className="min-w-0">{inline(it)}</span>
          </li>
        ))}
      </ul>
    );
  if (b.t === "ol")
    return (
      <ol className="space-y-1">
        {b.items.map((it, i) => (
          <li key={i} className="flex gap-2">
            <span className="mt-[2px] grid size-[18px] shrink-0 place-items-center rounded-full bg-brand/12 text-[10.5px] font-semibold tabular-nums text-brand">
              {i + 1}
            </span>
            <span className="min-w-0">{inline(it)}</span>
          </li>
        ))}
      </ol>
    );
  // a plain paragraph: "Lead: a; b; c." becomes a list (ReplyText); otherwise the sentence, its facts picked out
  if (!/[*`_]/.test(b.text) && /:\s.+;\s/.test(b.text)) return <ReplyText text={b.text} />;
  return <p>{inline(b.text)}</p>;
}

// **bold**, *italic* / _italic_, `code`
const MARK = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*\s][^*]*\*|(?<![\w])_[^_\s][^_]*_(?![\w]))/g;

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let at = 0;
  let k = 0;
  for (const m of text.matchAll(MARK)) {
    if (m.index! > at) out.push(...facts(text.slice(at, m.index), k++));
    const s = m[0];
    if (s.startsWith("**") || s.startsWith("__")) out.push(<strong key={`b${k++}`} className="font-semibold text-ink">{facts(s.slice(2, -2), k++)}</strong>);
    else if (s.startsWith("`")) out.push(<code key={`c${k++}`} className="rounded bg-panel-2 px-1 py-px font-mono text-[11.5px]">{s.slice(1, -1)}</code>);
    else out.push(<em key={`i${k++}`}>{facts(s.slice(1, -1), k++)}</em>);
    at = m.index! + s.length;
  }
  if (at < text.length) out.push(...facts(text.slice(at), k++));
  return out;
}

const DAYS = "(?:Mon|Tues?|Wed(?:nes)?|Thu(?:rs)?|Fri|Sat)(?:day)?\\b";
const CLOCK = "\\d{1,2}(?::\\d{2})?\\s?(?:am|pm)?";
const TIME = `(?:${DAYS}(?:,?\\s+(?:from\\s+)?${CLOCK}(?:\\s?(?:–|-|to)\\s?${CLOCK})?(?:\\s?(?:am|pm))?)?|\\b\\d{1,2}(?::\\d{2})?\\s?(?:am|pm)?(?:\\s?(?:–|-|to)\\s?\\d{1,2}(?::\\d{2})?)?\\s?(?:am|pm)\\b)`;
const ROOM = "(?:Room|Lab|Hall|Seminar Room)\\s+[A-Z]?-?\\d+[A-Z]?";
const FACT = new RegExp(`(\\b${ROOM}\\b)|(\\b${TIME})`, "g");

/** Times in medium weight, rooms as tags. */
function facts(text: string, key: number): ReactNode[] {
  const out: ReactNode[] = [];
  let at = 0;
  let k = 0;
  for (const m of text.matchAll(FACT)) {
    if (!m[0].trim()) continue;
    if (m.index! > at) out.push(text.slice(at, m.index));
    if (m[1])
      out.push(
        <span key={`${key}-r${k++}`} className="whitespace-nowrap rounded border border-line bg-panel-2 px-1 py-px text-[0.92em] text-ink">
          {m[0]}
        </span>,
      );
    else out.push(<span key={`${key}-t${k++}`} className="font-medium text-ink">{m[0]}</span>);
    at = m.index! + m[0].length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}
