import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { useApi } from "./hooks";
import { startWeek } from "./scheduling";

/** The institute, its calendar and a week to show: the week opens on this one (or the next at the weekend),
 * ``dates`` are its days' dates for the grid's headings, and ``dayName``/``slotLabel`` name days and hours. */
export function useWeek() {
  const { data: inst } = useApi(() => api.instance(), []);
  const { data: cal } = useApi(() => api.calendar(), []);
  const [week, setWeek] = useState<number | null>(null); // null until the calendar is in
  useEffect(() => {
    if (cal && week === null) setWeek(startWeek(cal));
  }, [cal]); // eslint-disable-line react-hooks/exhaustive-deps

  const dates = useMemo(() => {
    const w = week ? cal?.weeks[week - 1] : null;
    if (!w || !cal) return undefined;
    const today = new Date().toDateString();
    return Object.fromEntries(
      cal.days.map((d, i) => {
        const at = new Date(`${w.monday}T00:00:00`);
        at.setDate(at.getDate() + i);
        return [d, { label: at.toLocaleDateString(undefined, { day: "numeric", month: "short" }), today: at.toDateString() === today }];
      }),
    );
  }, [cal, week]);

  return {
    inst: inst ?? null,
    cal: cal ?? null,
    week,
    setWeek,
    dates,
    dayName: (d: string) => inst?.day_names[d] ?? d,
    slotLabel: (slot: number) => inst?.slots.find((s) => s.slot === slot)?.label ?? `slot ${slot}`,
  };
}
