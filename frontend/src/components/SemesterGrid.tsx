import clsx from "clsx";
import { colorFor } from "../lib/meta";
import type { SemCalendar, SemMeeting } from "../lib/types";

const DAY_START = 8 * 60 + 30;
const DAY_END = 21 * 60 + 15;
const PX = 0.95; // pixels per minute

function mins(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}

/** Side-by-side lanes for sessions that overlap in time. */
function lanes(ms: SemMeeting[]): { m: SemMeeting; lane: number; of: number }[] {
  const sorted = [...ms].sort((a, b) => mins(a.start) - mins(b.start) || mins(b.end) - mins(a.end));
  const out: { m: SemMeeting; lane: number; of: number }[] = [];
  let cluster: { m: SemMeeting; lane: number; of: number }[] = [];
  let clusterEnd = -1;
  const ends: number[] = [];
  const flush = () => {
    const n = Math.max(1, ...cluster.map((c) => c.lane + 1));
    cluster.forEach((c) => (c.of = n));
    out.push(...cluster);
    cluster = [];
    ends.length = 0;
  };
  for (const m of sorted) {
    if (mins(m.start) >= clusterEnd && cluster.length) flush();
    let lane = ends.findIndex((e) => e <= mins(m.start));
    if (lane < 0) lane = ends.length;
    ends[lane] = mins(m.end);
    cluster.push({ m, lane, of: 1 });
    clusterEnd = Math.max(clusterEnd, mins(m.end));
  }
  if (cluster.length) flush();
  return out;
}

export function SemesterGrid({
  calendar,
  meetings,
  changed,
  onPick,
}: {
  calendar: SemCalendar;
  meetings: SemMeeting[];
  changed?: Set<string>;
  onPick?: (m: SemMeeting) => void;
}) {
  const height = (DAY_END - DAY_START) * PX;
  const marks = calendar.lecture_slots.map(([a, b], i) => ({ a: mins(a), b: mins(b), label: `${a}`, n: i + 1 }));
  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[900px]" style={{ gridTemplateColumns: `56px repeat(${calendar.days.length}, minmax(0, 1fr))` }}>
        <div />
        {calendar.days.map((d) => (
          <div key={d} className="pb-2 text-center text-[12.5px] font-medium text-ink-2">
            {d}
            {calendar.mirror[d] && <span className="ml-1 text-[11px] font-normal text-ink-3">↔ {calendar.mirror[d]}</span>}
          </div>
        ))}
        <div className="relative" style={{ height }}>
          {marks.map((s) => (
            <div key={s.n} className="absolute right-2 text-right font-mono text-[10.5px] leading-tight text-ink-3" style={{ top: (s.a - DAY_START) * PX }}>
              {s.label}
              <div className="text-[9.5px]">slot {s.n}</div>
            </div>
          ))}
          <div className="absolute right-2 font-mono text-[10.5px] text-ink-3" style={{ top: (20 * 60 - DAY_START) * PX }}>
            20:00
          </div>
        </div>
        {calendar.days.map((d) => {
          const day = meetings.filter((m) => m.day === d);
          return (
            <div key={d} className="relative border-l border-line" style={{ height }}>
              {marks.map((s) => (
                <div key={s.n} className="absolute inset-x-0 border-t border-line/70" style={{ top: (s.a - DAY_START) * PX, height: (s.b - s.a) * PX }} />
              ))}
              {calendar.blocked
                .filter((w) => w.days.includes(d))
                .map((w, i) => (
                  <div
                    key={i}
                    className="hatch absolute inset-x-0 grid place-items-center text-[10.5px] text-ink-3"
                    style={{ top: (mins(w.start) - DAY_START) * PX, height: (mins(w.end) - mins(w.start)) * PX }}
                    title={w.reason}
                  >
                    free afternoon
                  </div>
                ))}
              <div className="absolute inset-x-0 grid place-items-center border-y border-line/70 bg-panel-2/60 text-[10px] text-ink-3" style={{ top: (13 * 60 + 5 - DAY_START) * PX, height: 55 * PX }}>
                lunch
              </div>
              {lanes(day).map(({ m, lane, of }) => {
                const c = colorFor(m.course);
                const top = (mins(m.start) - DAY_START) * PX;
                const h = Math.max(18, (mins(m.end) - mins(m.start)) * PX - 2);
                return (
                  <button
                    key={`${m.component}-${m.day}`}
                    onClick={() => onPick?.(m)}
                    title={`${m.course} ${m.name} · ${m.label} · ${m.start}-${m.end} · ${m.rooms.join(", ")}${m.half !== "full" ? ` · ${m.half}` : ""}`}
                    className={clsx(
                      "absolute overflow-hidden rounded border-l-[3px] px-1.5 py-1 text-left",
                      changed?.has(m.component) && "outline-2 outline-offset-1 outline-brand",
                    )}
                    style={{
                      top,
                      height: h,
                      left: `calc(${(lane / of) * 100}% + 2px)`,
                      width: `calc(${100 / of}% - 4px)`,
                      borderColor: c,
                      background: `color-mix(in oklab, ${c} ${m.kind === "lecture" ? 12 : 7}%, var(--panel))`,
                    }}
                  >
                    <p className="truncate text-[11px] font-semibold leading-tight">
                      {m.course}
                      {m.half !== "full" && <span className="ml-1 font-normal text-ink-3">{m.half}</span>}
                    </p>
                    {h > 34 && <p className="truncate text-[10.5px] leading-tight text-ink-2">{m.kind === "lecture" ? m.name : m.label}</p>}
                    {h > 50 && <p className="truncate text-[10px] leading-tight text-ink-3">{m.rooms.join(", ")}</p>}
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
