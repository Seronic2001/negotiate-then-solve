import { BookOpen, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { SemesterOverview } from "../lib/types";
import { Card, CardHeader } from "./ui";

const SHOWN = 40;

/** Next semester's courses from the offering document: who teaches what, for which groups.
 * Clicking a course code, a teacher or a group adds it to the preference being written. */
export function OfferingsCatalog({ overview, onPick }: { overview: SemesterOverview; onPick: (text: string) => void }) {
  const [q, setQ] = useState("");
  const cohortName = useMemo(() => Object.fromEntries(overview.cohorts.map((c) => [c.id, c.name])), [overview]);
  const rows = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return (overview.catalog ?? []).filter((c) => {
      if (!words.length) return true;
      const hay = [c.code, c.name, ...c.faculty, ...c.cohorts.map((x) => cohortName[x] ?? x)].join(" ").toLowerCase();
      return words.every((w) => hay.includes(w));
    });
  }, [overview, q, cohortName]);

  const chip = "rounded px-1.5 py-0.5 text-[12px] hover:bg-brand/10 hover:text-brand";
  return (
    <Card>
      <CardHeader icon={BookOpen} title="Next semester's courses" subtitle="Click a course, teacher or group to mention it" />
      <div className="border-b border-line p-3">
        <label className="flex items-center gap-2 rounded-md border border-line bg-panel px-2.5 focus-within:border-brand/60">
          <Search size={14} className="text-ink-3" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search a course, teacher or group"
            className="h-8 w-full bg-transparent text-[13px] outline-none"
          />
        </label>
        <p className="mt-1.5 text-[11.5px] text-ink-3">
          {rows.length} of {overview.catalog?.length ?? 0} courses
          {rows.length > SHOWN ? ` · first ${SHOWN} shown, search to narrow` : ""}
        </p>
      </div>
      <ul className="max-h-[480px] divide-y divide-line overflow-y-auto">
        {rows.slice(0, SHOWN).map((c) => (
          <li key={c.code} className="px-3 py-2.5">
            <div className="flex items-baseline gap-2">
              <button onClick={() => onPick(c.code)} className="shrink-0 font-mono text-[12px] text-brand hover:underline" title="Mention this course">
                {c.code}
              </button>
              <p className="min-w-0 truncate text-[13px] font-medium" title={c.name}>
                {c.name}
              </p>
            </div>
            {c.faculty.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1 text-ink-2">
                {c.faculty.map((f) => (
                  <button key={f} onClick={() => onPick(f)} className={chip} title="Mention this teacher">
                    {f}
                  </button>
                ))}
              </div>
            )}
            {c.cohorts.length > 0 && (
              <div className="mt-0.5 flex flex-wrap gap-1 text-ink-3">
                {c.cohorts.map((x) => (
                  <button key={x} onClick={() => onPick(cohortName[x] ?? x)} className={chip} title="Mention this group">
                    {cohortName[x] ?? x}
                  </button>
                ))}
              </div>
            )}
          </li>
        ))}
        {!rows.length && <li className="px-3 py-6 text-center text-[13px] text-ink-3">No course matches.</li>}
      </ul>
    </Card>
  );
}
