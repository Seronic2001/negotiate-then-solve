import clsx from "clsx";
import { FlaskConical, GraduationCap, MapPin } from "lucide-react";
import type { ReactNode } from "react";
import { colorFor } from "../lib/meta";
import type { InstanceView, TimetableEntry } from "../lib/types";

export function TimetableGrid({
  instance,
  entries,
  changed,
  onPick,
}: {
  instance: InstanceView;
  entries: TimetableEntry[];
  changed: Set<string>;
  onPick?: (e: TimetableEntry) => void;
}) {
  const { days, slots_per_day, lunch_slot } = instance.calendar;
  const cell = new Map<string, TimetableEntry[]>();
  for (const e of entries) {
    const k = `${e.day}:${e.slot}`;
    cell.set(k, [...(cell.get(k) ?? []), e]);
  }
  const covered = new Set<string>();
  for (const e of entries) for (let q = e.slot + 1; q < e.slot + e.duration; q++) covered.add(`${e.day}:${q}`);

  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[860px]" style={{ gridTemplateColumns: `72px repeat(${days.length}, minmax(0, 1fr))` }}>
        <div />
        {days.map((d) => (
          <div key={d} className="px-2 pb-3 text-center text-[12px] font-semibold text-ink-3">
            {instance.day_names[d] ?? d}
          </div>
        ))}
        {Array.from({ length: slots_per_day }, (_, s) => (
          <Row key={s}>
            <div className="pr-3 pt-2 text-right font-mono text-[11px] text-ink-3">{instance.slots[s]?.label}</div>
            {days.map((d) => {
              const list = cell.get(`${d}:${s}`) ?? [];
              const lunch = s === lunch_slot;
              return (
                <div
                  key={d}
                  className={clsx(
                    "relative min-h-[64px] border-l border-t border-line p-1",
                    lunch && "hatch",
                    covered.has(`${d}:${s}`) && !list.length && "bg-panel-2/40",
                  )}
                >
                  {lunch && !list.length && <span className="absolute inset-0 grid place-items-center text-[11px] text-ink-3">Lunch</span>}
                  <div className="space-y-1">
                      {list.map((e, i) => (
                        <Entry key={e.session} e={e} changed={changed.has(e.session)} index={i} onPick={onPick} />
                      ))}
                  </div>
                </div>
              );
            })}
          </Row>
        ))}
      </div>
    </div>
  );
}

function Row({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

function Entry({ e, changed, index, onPick }: { e: TimetableEntry; changed: boolean; index: number; onPick?: (e: TimetableEntry) => void }) {
  const c = colorFor(e.course);
  const Icon = e.kind === "practical" ? FlaskConical : GraduationCap;
  return (
    <button
      data-index={index}
      onClick={() => onPick?.(e)}
      className={clsx(
        "relative w-full overflow-hidden rounded border-l-[3px] px-2 py-1.5 text-left transition-colors",
        changed && "outline-2 outline-offset-1 outline-brand",
      )}
      style={{ borderColor: c, background: `color-mix(in oklab, ${c} 10%, var(--panel))` }}
      title={`${e.title} · ${e.faculty_name} · ${e.group_names.join(", ")} · ${e.room_name}`}
    >
      <p className="flex items-center gap-1 truncate text-[11.5px] font-semibold text-ink">
        <Icon size={11} style={{ color: c }} />
        {e.title}
        {e.duration > 1 && <span className="ml-auto text-[10px] font-normal text-ink-3">{e.duration}h</span>}
      </p>
      <p className="truncate text-[10.5px] text-ink-2">{e.faculty_name}</p>
      <p className="flex items-center gap-1 truncate text-[10px] text-ink-3">
        <MapPin size={9} />
        {e.room_name} · {e.group_names.join(", ")}
      </p>
    </button>
  );
}
