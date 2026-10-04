import clsx from "clsx";
import { BookOpen, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../lib/auth";
import type { SemesterOverview } from "../lib/types";
import { Card, CardHeader } from "./ui";

type Scope = "mine" | "sections" | "section" | "all";

const SHOWN = 40;

/** Next semester's courses from the offering document: who teaches what, for which groups.
 * Clicking a course code, a teacher or a group adds it to the preference being written. */
export function OfferingsCatalog({ overview, onPick }: { overview: SemesterOverview; onPick: (text: string) => void }) {
  const { user } = useAuth();
  const [q, setQ] = useState("");
  const cohortName = useMemo(() => Object.fromEntries(overview.cohorts.map((c) => [c.id, c.name])), [overview]);
  const all = useMemo(() => overview.catalog ?? [], [overview]);
  // who is looking decides what they see first: a teacher their courses, a class rep their section's
  const teaching = !!user && ["faculty", "guest_faculty"].includes(user.role) && all.some((c) => c.faculty.includes(user.name));
  const section = user?.role === "student" && user.id.startsWith("ST-") ? user.id.slice(3) : null;
  const scopes: { id: Scope; label: string }[] = teaching
    ? [{ id: "mine", label: "My courses" }, { id: "sections", label: "My sections" }, { id: "all", label: "All" }]
    : section
      ? [{ id: "section", label: "My section" }, { id: "all", label: "All" }]
      : [];
  const [scope, setScope] = useState<Scope>("all");
  useEffect(() => setScope(teaching ? "mine" : section ? "section" : "all"), [teaching, section]);
  const mySections = useMemo(
    () => new Set(all.filter((c) => user && c.faculty.includes(user.name)).flatMap((c) => c.cohorts)),
    [all, user],
  );
  const scoped = useMemo(() => {
    if (scope === "mine") return all.filter((c) => user && c.faculty.includes(user.name));
    if (scope === "sections") return all.filter((c) => c.cohorts.some((x) => mySections.has(x)));
    if (scope === "section") return all.filter((c) => section && c.cohorts.includes(section));
    return all;
  }, [all, scope, user, mySections, section]);
  const rows = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return scoped.filter((c) => {
      if (!words.length) return true;
      const hay = [c.code, c.name, ...c.faculty, ...c.cohorts.map((x) => cohortName[x] ?? x)].join(" ").toLowerCase();
      return words.every((w) => hay.includes(w));
    });
  }, [scoped, q, cohortName]);

  const chip = "rounded px-1.5 py-0.5 text-[12px] hover:bg-brand/10 hover:text-brand";
  return (
    <Card>
      <CardHeader icon={BookOpen} title="Next semester's courses" subtitle="Click a course, teacher or group to mention it" />
      <div className="border-b border-line p-3">
        {scopes.length > 0 && (
          <div className="mb-2 flex gap-1">
            {scopes.map((x) => (
              <button
                key={x.id}
                onClick={() => setScope(x.id)}
                className={clsx("rounded-md px-2.5 py-1 text-[12px]", scope === x.id ? "bg-panel-2 font-medium text-ink" : "text-ink-3 hover:text-ink")}
              >
                {x.label}
              </button>
            ))}
          </div>
        )}
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
          {rows.length} of {scoped.length} courses{scope !== "all" ? ` (${all.length} in all)` : ""}
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
