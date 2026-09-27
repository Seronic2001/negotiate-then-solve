import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  BadgeCheck,
  BookOpen,
  CalendarDays,
  ChevronsUpDown,
  FileUp,
  Hammer,
  FlaskConical,
  Home,
  Inbox,
  ListChecks,
  LogOut,
  Menu,
  Moon,
  Music,
  Network,
  Plus,
  Scale,
  Search,
  SlidersHorizontal,
  Sun,
  Waypoints,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi, useHotkey } from "../lib/hooks";
import { ROLE_LABEL, STATUS } from "../lib/meta";
import { useTheme } from "../lib/theme";
import type { Overview, View } from "../lib/types";
import { Avatar, Kbd, LiveDot, Mark } from "./ui";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  view: View;
  badge?: "inbox" | "approvals";
  group: "main" | "semester" | "reference" | "research";
}

export const NAV: NavItem[] = [
  { to: "/", label: "Home", icon: Home, group: "main", view: "home" },
  { to: "/requests", label: "Requests", icon: ListChecks, group: "main", view: "requests" },
  { to: "/inbox", label: "Inbox", icon: Inbox, group: "main", view: "inbox", badge: "inbox" },
  { to: "/approvals", label: "Approvals", icon: BadgeCheck, group: "main", view: "approvals", badge: "approvals" },
  { to: "/documents", label: "Policy documents", icon: FileUp, group: "main", view: "documents" },
  { to: "/semester", label: "Build timetable", icon: Hammer, group: "semester", view: "semester" },
  { to: "/preferences", label: "Semester preferences", icon: SlidersHorizontal, group: "semester", view: "prefs" },
  { to: "/clubs", label: "Club activities", icon: Music, group: "semester", view: "clubs" },
  { to: "/timetable", label: "Timetable", icon: CalendarDays, group: "main", view: "timetable" },
  { to: "/fairness", label: "Fairness", icon: Scale, group: "reference", view: "fairness" },
  { to: "/policy", label: "Handbook", icon: BookOpen, group: "reference", view: "handbook" },
  { to: "/transparency", label: "How it works", icon: Waypoints, group: "reference", view: "how" },
  { to: "/graph", label: "Knowledge graph", icon: Network, group: "research", view: "graph" },
  { to: "/observability", label: "System health", icon: Activity, group: "research", view: "health" },
  { to: "/experiments", label: "Experiments", icon: FlaskConical, group: "research", view: "experiments" },
];

const GROUPS: { id: NavItem["group"]; label?: string }[] = [
  { id: "main" },
  { id: "semester", label: "Semester" },
  { id: "reference", label: "Reference" },
  { id: "research", label: "Research" },
];

export function Shell({ children }: { children: ReactNode }) {
  const { user, sees } = useAuth();
  const [palette, setPalette] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const location = useLocation();
  const { data: ov } = useApi(() => api.overview(), [user?.id], 4000);
  useHotkey("k", () => setPalette((p) => !p));
  useEffect(() => setDrawer(false), [location.pathname]);

  const items = NAV.filter((n) => sees(n.view));
  const sidebar = <Sidebar items={items} ov={ov} onSearch={() => setPalette(true)} />;

  return (
    <div className="flex h-full">
      <aside className="hidden h-full w-60 shrink-0 border-r border-line bg-panel md:block">{sidebar}</aside>

      <AnimatePresence>
        {drawer && (
          <motion.div className="fixed inset-0 z-40 bg-ink/20 md:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setDrawer(false)}>
            <motion.aside
              initial={{ x: -260 }}
              animate={{ x: 0 }}
              exit={{ x: -260 }}
              transition={{ type: "tween", duration: 0.2 }}
              onClick={(e) => e.stopPropagation()}
              className="h-full w-64 border-r border-line bg-panel"
            >
              {sidebar}
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-panel px-4 md:hidden">
          <button onClick={() => setDrawer(true)} className="grid size-8 place-items-center rounded-md text-ink-2 hover:bg-panel-2" aria-label="Menu">
            <Menu size={18} />
          </button>
          <Mark size={20} />
          <span className="font-serif text-[15px] font-semibold">Negotiate, Then Solve</span>
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1280px] px-4 py-7 sm:px-8">{children}</div>
        </main>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} items={items} />
    </div>
  );
}

function Sidebar({ items, ov, onSearch }: { items: NavItem[]; ov: Overview | null; onSearch: () => void }) {
  const { sees } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const badge = (b?: NavItem["badge"]) => (b === "inbox" ? ov?.my_inbox : b === "approvals" ? ov?.pending_approvals : 0) ?? 0;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2.5 px-4 pb-4 pt-5">
        <Mark />
        <div className="min-w-0">
          <p className="truncate font-serif text-[15.5px] leading-tight font-semibold">Negotiate, Then Solve</p>
          <p className="truncate text-[11.5px] text-ink-3">{ov?.department ?? "Timetabling"}</p>
        </div>
      </div>

      <div className="space-y-1.5 px-3">
        {sees("new") && (
          <button
            onClick={() => navigate("/new")}
            className="flex h-8 w-full items-center justify-center gap-1.5 rounded-md bg-brand text-[13px] font-medium text-panel hover:bg-brand/90"
          >
            <Plus size={15} /> New request
          </button>
        )}
        <button onClick={onSearch} className="flex h-8 w-full items-center gap-2 rounded-md border border-line px-2.5 text-[13px] text-ink-3 hover:bg-panel-2">
          <Search size={14} />
          <span className="flex-1 text-left">Search</span>
          <Kbd>Ctrl K</Kbd>
        </button>
      </div>

      <nav className="mt-4 flex-1 space-y-4 overflow-y-auto px-3">
        {GROUPS.map((g) => {
          const list = items.filter((i) => i.group === g.id);
          if (!list.length) return null;
          return (
            <div key={g.id}>
              {g.label && <p className="mb-1 px-2.5 text-[11px] font-medium text-ink-3">{g.label}</p>}
              {list.map((n) => {
                const active = n.to === "/" ? location.pathname === "/" : location.pathname.startsWith(n.to);
                const count = badge(n.badge);
                return (
                  <NavLink
                    key={n.to}
                    to={n.to}
                    className={clsx(
                      "flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13.5px]",
                      active ? "bg-panel-2 font-medium text-ink" : "text-ink-2 hover:bg-panel-2/60 hover:text-ink",
                    )}
                  >
                    <n.icon size={16} className={active ? "text-brand" : "text-ink-3"} />
                    <span className="flex-1 truncate">{n.label}</span>
                    {count > 0 && <span className="rounded bg-brand px-1.5 text-[11px] font-semibold tabular-nums text-panel">{count}</span>}
                  </NavLink>
                );
              })}
            </div>
          );
        })}
      </nav>

      <div className="border-t border-line px-3 py-3">
        <p className="mb-2 flex items-center gap-2 px-2.5 text-[11.5px] text-ink-3">
          <LiveDot tone={ov?.seeding ? "warn" : "ok"} pulse={!!ov?.seeding} />
          {ov?.seeding ? "Loading demo history…" : ov?.published_version != null ? `Timetable v${ov.published_version} published` : "Connecting…"}
        </p>
        <Account />
      </div>
    </div>
  );
}

function Account() {
  const { user, signIn, signOut } = useAuth();
  const { theme, toggle } = useTheme();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { data } = useApi(() => (open ? api.personas() : Promise.resolve(null)), [open]);
  useEffect(() => {
    if (!open) return;
    const on = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest("[data-account]")) setOpen(false);
    };
    window.addEventListener("mousedown", on);
    return () => window.removeEventListener("mousedown", on);
  }, [open]);
  if (!user) return null;

  return (
    <div className="relative flex items-center gap-1" data-account>
      <button onClick={() => setOpen(!open)} className="flex min-w-0 flex-1 items-center gap-2.5 rounded-md px-1.5 py-1.5 text-left hover:bg-panel-2">
        <Avatar name={user.name} id={user.id} size={28} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium leading-tight">{user.name}</p>
          <p className="truncate text-[11.5px] leading-tight text-ink-3">{ROLE_LABEL[user.role]}</p>
        </div>
        <ChevronsUpDown size={14} className="shrink-0 text-ink-3" />
      </button>
      <button onClick={toggle} className="grid size-8 shrink-0 place-items-center rounded-md text-ink-3 hover:bg-panel-2 hover:text-ink" title={theme === "dark" ? "Light theme" : "Dark theme"}>
        {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.12 }}
            className="absolute bottom-12 left-0 z-30 w-64 overflow-hidden rounded-lg border border-line bg-panel shadow-lg"
          >
            <p className="border-b border-line px-3 py-2 text-[11.5px] text-ink-3">Switch person (demo sign-in)</p>
            <div className="max-h-72 overflow-y-auto p-1">
              {data?.map((p) => (
                <button
                  key={p.id}
                  onClick={async () => {
                    await signIn(p.id);
                    setOpen(false);
                    navigate("/");
                  }}
                  className={clsx("flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-panel-2", p.id === user.id && "bg-panel-2")}
                >
                  <Avatar name={p.name} id={p.id} size={24} />
                  <div className="min-w-0">
                    <p className="truncate text-[13px]">{p.name}</p>
                    <p className="truncate text-[11px] text-ink-3">{ROLE_LABEL[p.role]}</p>
                  </div>
                </button>
              ))}
            </div>
            <button onClick={signOut} className="flex w-full items-center gap-2 border-t border-line px-3 py-2 text-[13px] text-ink-2 hover:bg-panel-2">
              <LogOut size={14} /> Sign out
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function CommandPalette({ open, onClose, items }: { open: boolean; onClose: () => void; items: NavItem[] }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const navigate = useNavigate();
  const { can } = useAuth();
  const { data: cases } = useApi(() => (open ? api.cases(can("see_all") ? "all" : "mine") : Promise.resolve([])), [open]);
  const results = useMemo(() => {
    const ql = q.toLowerCase();
    const pages = items.filter((i) => i.label.toLowerCase().includes(ql)).map((i) => ({ key: i.to, label: i.label, hint: "Page", icon: i.icon, go: i.to }));
    const cs = (cases ?? [])
      .filter((c) => !ql || `${c.id} ${c.text} ${c.sender_name}`.toLowerCase().includes(ql))
      .slice(0, 8)
      .map((c) => ({ key: c.id, label: c.text, hint: STATUS[c.status].label, icon: STATUS[c.status].icon, go: `/requests/${c.id}` }));
    return [...pages, ...cs];
  }, [q, items, cases]);

  useEffect(() => {
    setSel(0);
  }, [q, open]);

  const go = (to: string) => {
    navigate(to);
    onClose();
    setQ("");
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 flex items-start justify-center bg-ink/20 px-4 pt-[14vh]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.12 }} onClick={onClose}>
          <div onClick={(e) => e.stopPropagation()} className="w-full max-w-lg overflow-hidden rounded-lg border border-line bg-panel shadow-xl">
            <div className="flex items-center gap-2.5 border-b border-line px-3.5">
              <Search size={16} className="text-ink-3" />
              <input
                autoFocus
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown") setSel((s) => Math.min(results.length - 1, s + 1));
                  if (e.key === "ArrowUp") setSel((s) => Math.max(0, s - 1));
                  if (e.key === "Escape") onClose();
                  if (e.key === "Enter" && results[sel]) go(results[sel].go);
                }}
                placeholder="Go to a page or find a request"
                className="h-12 flex-1 bg-transparent text-[14.5px] outline-none placeholder:text-ink-3"
              />
              <button onClick={onClose} className="text-ink-3 hover:text-ink" aria-label="Close">
                <X size={16} />
              </button>
            </div>
            <div className="max-h-96 overflow-y-auto p-1.5">
              {results.map((r, i) => (
                <button
                  key={r.key}
                  onMouseEnter={() => setSel(i)}
                  onClick={() => go(r.go)}
                  className={clsx("flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-[13.5px]", i === sel ? "bg-panel-2 text-ink" : "text-ink-2")}
                >
                  <r.icon size={15} className="shrink-0 text-ink-3" />
                  <span className="flex-1 truncate">{r.label}</span>
                  <span className="shrink-0 text-[12px] text-ink-3">{r.hint}</span>
                </button>
              ))}
              {!results.length && <p className="px-3 py-8 text-center text-[13px] text-ink-3">Nothing matches “{q}”.</p>}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
