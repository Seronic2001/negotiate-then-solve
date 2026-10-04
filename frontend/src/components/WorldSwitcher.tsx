import clsx from "clsx";
import { Building2, Check, ChevronsUpDown, FileUp, Loader2, RotateCcw, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { api, currentWorld, setCurrentWorld, type WorldRow } from "../lib/api";
import { useApi } from "../lib/hooks";

const readFile = (f: File) =>
  new Promise<string>((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1] ?? "");
    r.onerror = () => reject(r.error);
    r.readAsDataURL(f);
  });

export function worldLine(w: WorldRow): string {
  if (w.status === "starting") return "being built…";
  if (w.status === "error") return w.error ?? "could not be built";
  return `${w.people} people · ${w.sections} sections · ${w.sessions} classes · ${w.rooms} rooms${w.seeding ? " · replaying history" : ""}`;
}

/** The timetable office moves between worlds, and makes new ones from an offering document or the demo campus. */
export function WorldSwitcher({ name }: { name: string }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const { data: worlds, refresh } = useApi(() => api.worlds(), [open], open ? 3000 : undefined);
  const here = currentWorld();

  const go = (w: WorldRow) => {
    if (w.status !== "ready" || w.id === here) return;
    setCurrentWorld(w.id);
    window.location.assign("/"); // every page reloads in the new world; the timetable office exists in all of them
  };
  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-1 text-left text-[11.5px] text-ink-3 hover:text-ink" title="Switch world">
        <span className="truncate">{name}</span>
        <ChevronsUpDown size={11} className="shrink-0" />
      </button>
      {open && (
        <div className="absolute left-0 top-6 z-40 w-80 overflow-hidden rounded-lg border border-line bg-panel shadow-lg">
          <p className="border-b border-line px-3 py-2 text-[11.5px] text-ink-3">Worlds: each has its own people, timetable and history</p>
          <ul className="max-h-80 overflow-y-auto p-1">
            {(worlds ?? []).map((w) => (
              <li key={w.id} className="group flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-panel-2">
                <button onClick={() => go(w)} disabled={w.status !== "ready"} className="flex min-w-0 flex-1 items-start gap-2 text-left disabled:cursor-default">
                  {w.status === "starting" ? (
                    <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin text-ink-3" />
                  ) : w.id === here ? (
                    <Check size={14} className="mt-0.5 shrink-0 text-ok" />
                  ) : (
                    <Building2 size={14} className="mt-0.5 shrink-0 text-ink-3" />
                  )}
                  <div className="min-w-0">
                    <p className="truncate text-[13px]">{w.name}</p>
                    <p className={clsx("truncate text-[11px]", w.status === "error" ? "text-bad" : "text-ink-3")}>{worldLine(w)}</p>
                  </div>
                </button>
                {w.kind !== "demo" && w.id !== here && (
                  <button
                    title="Delete this world"
                    onClick={() => window.confirm(`Delete the world "${w.name}"? Its history is lost.`) && void act("del", () => api.deleteWorld(w.id))}
                    className="grid size-6 shrink-0 place-items-center rounded text-ink-3 opacity-0 hover:text-bad group-hover:opacity-100"
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </li>
            ))}
          </ul>
          <div className="space-y-1 border-t border-line p-2">
            <input
              ref={file}
              type="file"
              className="hidden"
              accept=".pdf,.html,.htm,.txt,.png,.jpg,.jpeg"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) await act("upload", async () => api.newWorld({ name: f.name.replace(/\.[^.]+$/, ""), filename: f.name, data: await readFile(f) }));
                if (file.current) file.current.value = "";
              }}
            />
            <button onClick={() => file.current?.click()} disabled={!!busy} className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-panel-2">
              {busy === "upload" ? <Loader2 size={14} className="animate-spin" /> : <FileUp size={14} className="text-ink-3" />} New world from an offering document
            </button>
            {!(worlds ?? []).some((w) => w.source.startsWith("Campus (demo)")) && (
              <button onClick={() => void act("campus", () => api.newWorld({ preset: "campus" }))} disabled={!!busy} className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-panel-2">
                {busy === "campus" ? <Loader2 size={14} className="animate-spin" /> : <Building2 size={14} className="text-ink-3" />} Add the demo campus (4-year B.Tech)
              </button>
            )}
            <button
              onClick={() =>
                window.confirm(
                  `Restore "${name}" to its demo state? It goes back to how it stood once the demo history had finished: every request, approval, reply and semester-plan change made since is removed. Study records are kept.`,
                ) &&
                void act("reset", async () => {
                  await api.reset();
                  window.location.assign("/");
                })
              }
              disabled={!!busy}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-panel-2"
            >
              {busy === "reset" ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} className="text-ink-3" />} Restore this world to its demo state
            </button>
            {error && <p className="px-2 text-[12px] text-bad">{error}</p>}
          </div>
        </div>
      )}
    </div>
  );
}
