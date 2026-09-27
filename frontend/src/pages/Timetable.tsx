import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import { Clock, FlaskConical, GitBranch, History, MapPin, RotateCcw, Users, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { TimetableGrid } from "../components/TimetableGrid";
import { Badge, Button, Card, CardHeader, PageHeader, Skeleton, Tabs, Toast } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { ago } from "../lib/meta";
import type { TimetableEntry } from "../lib/types";

type By = "all" | "faculty" | "group" | "room";

export default function Timetable() {
  const { user, can } = useAuth();
  const { data: inst } = useApi(() => api.instance(), []);
  const { data: versions, refresh: refreshVersions } = useApi(() => api.versions(), [], 5000);
  const [version, setVersion] = useState<number | null>(null);
  const { data: tt, refresh } = useApi(() => api.timetable(version ? { version } : {}), [version], version ? undefined : 5000);
  const isTeacher = !!inst?.faculty.some((f) => f.id === user?.id);
  const [by, setBy] = useState<By>(isTeacher ? "faculty" : "all");
  const [who, setWho] = useState<string>("");
  const [picked, setPicked] = useState<TimetableEntry | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!inst) return;
    if (isTeacher) {
      setBy("faculty");
      setWho(user!.id);
    } else if (user?.role === "student") {
      setBy("group");
      setWho(user.id.replace("ST-", ""));
    }
  }, [inst, isTeacher, user]);

  const options = useMemo(() => {
    if (!inst) return [];
    if (by === "faculty") return inst.faculty.map((f) => ({ id: f.id, label: f.name }));
    if (by === "group") return inst.groups.map((g) => ({ id: g.id, label: g.name }));
    if (by === "room") return inst.rooms.map((r) => ({ id: r.id, label: `${r.name}${r.equipment.length ? ` · ${r.equipment.join(", ")}` : ""}` }));
    return [];
  }, [inst, by]);

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
            Timetable
            {tt && (
              <Badge tone="muted" className="text-[12.5px]">
                v{tt.version}
                {tt.week ? ` · week ${tt.week}` : " · semester"}
              </Badge>
            )}
          </span>
        }
        subtitle="Every version is kept. Classes that moved in this version are outlined."
        actions={
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
        }
      />
      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
            <Tabs
              tabs={[
                { id: "all", label: "Everything" },
                { id: "faculty", label: "Teacher" },
                { id: "group", label: "Section" },
                { id: "room", label: "Room" },
              ]}
              value={by}
              onChange={setBy}
            />
            {by !== "all" && (
              <select value={who} onChange={(e) => setWho(e.target.value)} className="h-8 rounded-md border border-line bg-panel px-2.5 text-[13px] outline-none">
                {options.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.label}
                  </option>
                ))}
              </select>
            )}
            <span className="ml-auto text-[12.5px] text-ink-3">
              {entries.length} sessions · {tt?.changed.length ?? 0} changed in this version
            </span>
          </div>
          <div className="p-4">{inst && tt ? <TimetableGrid instance={inst} entries={entries} changed={changed} onPick={setPicked} /> : <Skeleton className="h-[560px]" />}</div>
        </Card>

        <Card className="h-fit">
          <CardHeader icon={History} title="Version history" subtitle="Rollback publishes a copy of an older version" />
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
              </div>
            ))}
          </div>
        </Card>
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
