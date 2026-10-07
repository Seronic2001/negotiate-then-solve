import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import { Clock, FlaskConical, GitBranch, History, MapPin, RotateCcw, Users, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { TimetableGrid } from "../components/TimetableGrid";
import { WeekStepper } from "../components/WeekStepper";
import { Badge, Button, Card, CardHeader, PageHeader, Skeleton, Tabs, Toast } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { ago } from "../lib/meta";
import type { TimetableEntry } from "../lib/types";

type By = "all" | "faculty" | "group" | "room";

export default function Timetable() {
  const { user, can, sees } = useAuth();
  const office = sees("history"); // versions, proposals and rollback; everyone else sees the latest published
  const { data: inst } = useApi(() => api.instance(), []);
  const { data: versions, refresh: refreshVersions } = useApi(() => (office ? api.versions() : Promise.resolve([])), [office], office ? 5000 : undefined);
  const [version, setVersion] = useState<number | null>(null);
  const { data: cal } = useApi(() => api.calendar(), []);
  const [week, setWeek] = useState<number | null>(null); // null: the semester timetable, every week without its own changes
  const [weekSet, setWeekSet] = useState(false);
  useEffect(() => {
    if (cal && !weekSet) {
      setWeek(cal.current_week); // open on this week
      setWeekSet(true);
    }
  }, [cal, weekSet]);
  const { data: tt, refresh } = useApi(() => api.timetable(version ? { version } : { week }), [version, week], version ? undefined : 5000);
  const isTeacher = !!inst?.faculty.some((f) => f.id === user?.id);
  // what each person browses: the office (and HoD, Dean) everything; a teacher their own classes,
  // the sections they teach and the rooms; a class rep their section and its teachers
  const scope: "all" | "teacher" | "student" | "other" =
    office || user?.role === "hod" || user?.role === "dean" ? "all" : isTeacher ? "teacher" : user?.role === "student" ? "student" : "other";
  const myGroup = user?.role === "student" ? user.id.replace("ST-", "") : null;
  const tabs = useMemo((): { id: By; label: string }[] => {
    if (scope === "teacher") return [{ id: "faculty", label: "My classes" }, { id: "group", label: "Sections I teach" }, { id: "room", label: "Rooms" }];
    if (scope === "student") return [{ id: "group", label: "My section" }, { id: "faculty", label: "My teachers" }];
    if (scope === "other") return [{ id: "all", label: "Everything" }, { id: "room", label: "Rooms" }];
    return [{ id: "all", label: "Everything" }, { id: "faculty", label: "Teacher" }, { id: "group", label: "Section" }, { id: "room", label: "Room" }];
  }, [scope]);
  const [by, setBy] = useState<By>("all");
  const [who, setWho] = useState<string>("");
  const [picked, setPicked] = useState<TimetableEntry | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!inst) return;
    if (scope === "teacher") {
      setBy("faculty");
      setWho(user!.id);
    } else if (scope === "student") {
      setBy("group");
      setWho(myGroup!);
    } else setBy("all");
  }, [inst, scope, user, myGroup]);

  const options = useMemo(() => {
    if (!inst) return [];
    const all = tt?.entries ?? [];
    if (by === "faculty") {
      if (scope === "teacher") return inst.faculty.filter((f) => f.id === user?.id).map((f) => ({ id: f.id, label: f.name }));
      const mine = scope === "student" ? new Set(all.filter((e) => e.groups.includes(myGroup!)).map((e) => e.faculty)) : null;
      return inst.faculty.filter((f) => !mine || mine.has(f.id)).map((f) => ({ id: f.id, label: f.name }));
    }
    if (by === "group") {
      if (scope === "student") return inst.groups.filter((g) => g.id === myGroup).map((g) => ({ id: g.id, label: g.name }));
      const taught = scope === "teacher" ? new Set(all.filter((e) => e.faculty === user?.id).flatMap((e) => e.groups)) : null;
      return inst.groups.filter((g) => !taught || taught.has(g.id)).map((g) => ({ id: g.id, label: g.name }));
    }
    if (by === "room") return inst.rooms.map((r) => ({ id: r.id, label: `${r.name}${r.equipment.length ? ` · ${r.equipment.join(", ")}` : ""}` }));
    return [];
  }, [inst, tt, by, scope, user, myGroup]);

  useEffect(() => {
    if (by !== "all" && options.length && !options.some((o) => o.id === who)) setWho(options[0].id);
  }, [by, options, who]);

  const entries = useMemo(() => {
    const all = tt?.entries ?? [];
    if (by === "faculty") return all.filter((e) => e.faculty === who);
    if (by === "group") return all.filter((e) => e.groups.includes(who));
    if (by === "room") return all.filter((e) => e.room === who);
    return all;
  }, [tt, by, who]);
  const changed = useMemo(() => new Set(tt?.changed ?? []), [tt]);

  return (
    <>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-3">
            {week && !version ? `Timetable · week ${week}` : "Timetable"}
            {tt && office && (
              <Badge tone="muted" className="text-[12.5px]">
                v{tt.version}
                {tt.week ? ` · week ${tt.week}` : " · semester"}
              </Badge>
            )}
          </span>
        }
        subtitle={
          office
            ? "The live timetable that requests and negotiations change. A change for one week (an absence, a closed room) shows under that week. Every version is kept; classes that moved in this version are outlined. The semester plan is built separately (Semester plan)."
            : "The live timetable: requests and negotiations change it. A change for one week shows under that week. Classes that moved in the latest change are outlined."
        }
        actions={
          office && (
            <select
              value={version ?? ""}
              onChange={(e) => setVersion(e.target.value ? +e.target.value : null)}
              className="h-9 rounded-md border border-line bg-panel px-2.5 text-[13px] outline-none"
            >
              <option value="">Latest published</option>
              {versions?.map((v) => (
                <option key={v.version} value={v.version}>
                  v{v.version}
                  {v.week ? ` (week ${v.week})` : ""} {v.published ? "" : "· proposed"}
                </option>
              ))}
            </select>
          )
        }
      />
      {(tt?.cancelled.length ?? 0) > 0 && (
        <div className="mb-4 rounded-lg border border-bad/40 bg-bad/5 px-4 py-3 text-[13px]">
          <p className="font-medium">
            Not held in week {tt!.week}: {tt!.cancelled.length} {tt!.cancelled.length === 1 ? "class" : "classes"} (a make-up is owed)
          </p>
          <p className="mt-1 text-ink-2">
            {tt!.cancelled.map((c) => `${c.session_name.replace(/^the /, "")} (${c.faculty_name})`).join(" · ")}
          </p>
        </div>
      )}
      <div className={clsx("grid gap-6", office && "2xl:grid-cols-[minmax(0,1fr)_320px]")}>
        <Card>
          <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
            <Tabs
              tabs={tabs}
              value={by}
              onChange={setBy}
            />
            {!version && cal && <WeekStepper cal={cal} week={week} onChange={setWeek} />}
            {by !== "all" && options.length > 1 && (
              <select value={who} onChange={(e) => setWho(e.target.value)} className="h-8 rounded-md border border-line bg-panel px-2.5 text-[13px] outline-none">
                {options.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
            )}
            {scope === "teacher" && by === "group" && (
              <span className="text-[12.5px] text-ink-3">The whole week of this section, every teacher: when its students are busy or free.</span>
            )}
            {scope === "student" && by === "faculty" && <span className="text-[12.5px] text-ink-3">Everything this teacher teaches, not only your section.</span>}
            <span className="ml-auto text-[12.5px] text-ink-3">
              {entries.length} sessions · {tt?.changed.length ?? 0} changed {office ? "in this version" : "in the latest change"}
            </span>
          </div>
          <div className="p-4">{inst && tt ? <TimetableGrid instance={inst} entries={entries} changed={changed} onPick={setPicked} /> : <Skeleton className="h-[560px]" />}</div>
        </Card>

        {office && (
          <Card className="h-fit">
            <CardHeader icon={History} title="Version history" subtitle="Rollback publishes a copy of an older version. A change that also reaches a week with its own changes saves that week as the next number." />
            <div className="max-h-[640px] space-y-0 overflow-y-auto p-3">
              {versions?.map((v, i) => (
                <div key={v.version} data-index={i} className={clsx("relative rounded-md px-3 py-2", tt?.version === v.version && "bg-panel-2")}>
                  <div className="flex items-center gap-2">
                    <GitBranch size={14} className={v.published ? "text-ok" : "text-ink-3"} />
                    <button onClick={() => setVersion(v.version)} className="font-medium hover:text-brand">
                      v{v.version}
                    </button>
                    {v.week && <Badge tone="info">week {v.week}</Badge>}
                    <Badge tone={v.published ? "ok" : "muted"}>{v.published ? "published" : "proposed"}</Badge>
                    {can("approve") && v.published && tt?.version !== v.version && (
                      <button
                        title="Roll back to this version"
                        onClick={async () => {
                          const r = await api.rollback(v.version);
                          setToast(`Rolled back: published v${r.version} as a copy of v${v.version}.`);
                          setVersion(null);
                          await Promise.all([refresh(), refreshVersions()]);
                        }}
                        className="ml-auto grid size-7 place-items-center rounded-lg text-ink-3 hover:bg-panel-2 hover:text-brand"
                      >
                        <RotateCcw size={14} />
                      </button>
                    )}
                  </div>
                  <p className="mt-1 pl-6 text-[11.5px] text-ink-3">
                    {v.approved_by_name ? `approved by ${v.approved_by_name}` : "awaiting approval"} · {v.case ?? ""} · {ago(v.created_at)}
                  </p>
                  {v.carried.length > 0 && (
                    <p className="mt-0.5 pl-6 text-[11.5px] text-ink-3">
                      also updates{" "}
                      {v.carried.map((c, j) => (
                        <span key={c.version}>
                          {j > 0 && ", "}
                          <button onClick={() => setVersion(c.version)} className="underline decoration-dotted hover:text-brand">
                            week {c.week}
                          </button>{" "}
                          as v{c.version}
                        </span>
                      ))}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>

      <AnimatePresence>
        {picked && (
          <motion.div className="fixed inset-0 z-40 bg-ink/20" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setPicked(null)}>
            <motion.div
              initial={{ x: 400 }}
              animate={{ x: 0 }}
              exit={{ x: 400 }}
              transition={{ type: "tween", duration: 0.2 }}
              onClick={(e) => e.stopPropagation()}
              className="absolute inset-y-0 right-0 w-full max-w-sm border-l border-line bg-panel p-6 shadow-lg"
            >
              <button onClick={() => setPicked(null)} className="absolute right-4 top-4 grid size-8 place-items-center rounded-lg text-ink-3 hover:bg-panel-2">
                <X size={16} />
              </button>
              <Badge tone={picked.kind === "practical" ? "warn" : "info"}>
                {picked.kind === "practical" && <FlaskConical size={11} />} {picked.kind}
              </Badge>
              {picked.extra && (
                <Badge tone="brand" className="ml-1.5">
                  extra class, week {tt?.week}
                </Badge>
              )}
              <h3 className="mt-3 text-xl font-semibold">{picked.title}</h3>
              <p className="font-mono text-[12px] text-ink-3">{picked.session}</p>
              <div className="mt-6 space-y-3 text-[14px]">
                <p className="flex items-center gap-3">
                  <Clock size={16} className="text-ink-3" /> {inst?.day_names[picked.day]} · {inst?.slots[picked.slot]?.label} · {picked.duration}h
                </p>
                <p className="flex items-center gap-3">
                  <MapPin size={16} className="text-ink-3" /> {picked.room_name}
                </p>
                <p className="flex items-center gap-3">
                  <Users size={16} className="text-ink-3" /> {picked.faculty_name} · {picked.group_names.join(", ")}
                </p>
              </div>
              {changed.has(picked.session) && <p className="mt-6 rounded-md border border-brand/40 p-3 text-[13px]">This session moved in version {tt?.version}.</p>}
              <Button className="mt-6 w-full" onClick={() => setPicked(null)}>
                Close
              </Button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
      <Toast message={toast} onDone={() => setToast(null)} />
    </>
  );
}
