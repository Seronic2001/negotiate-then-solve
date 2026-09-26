import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  BadgeCheck,
  BookOpen,
  CalendarDays,
  ChevronsLeft,
  Eye,
  FlaskConical,
  Inbox,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Moon,
  Network,
  PenSquare,
  Scale,
  Search,
  Sun,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth, type Capability } from "../lib/auth";
import { useApi, useHotkey } from "../lib/hooks";
import { ROLE_LABEL, STATUS } from "../lib/meta";
import { useTheme } from "../lib/theme";
import type { Persona } from "../lib/types";
import { Avatar, Kbd, LiveDot } from "./ui";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  need?: Capability;
  badge?: "inbox" | "approvals";
  section: "Work" | "Timetable" | "Insight";
}

export const NAV: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, section: "Work" },
  { to: "/new", label: "New request", icon: PenSquare, section: "Work", need: "request" },
  { to: "/requests", label: "Requests", icon: ListChecks, section: "Work" },
  { to: "/inbox", label: "Negotiation inbox", icon: Inbox, section: "Work", badge: "inbox" },
  { to: "/approvals", label: "Approvals", icon: BadgeCheck, section: "Work", need: "approve", badge: "approvals" },
  { to: "/timetable", label: "Timetable", icon: CalendarDays, section: "Timetable" },
  { to: "/fairness", label: "Fairness ledger", icon: Scale, section: "Timetable" },
  { to: "/policy", label: "Handbook & retrieval", icon: BookOpen, section: "Timetable" },
  { to: "/transparency", label: "How decisions work", icon: Eye, section: "Insight" },
  { to: "/graph", label: "Knowledge graph", icon: Network, section: "Insight", need: "observe" },
  { to: "/observability", label: "Observability", icon: Activity, section: "Insight", need: "observe" },
  { to: "/experiments", label: "Experiments", icon: FlaskConical, section: "Insight", need: "observe" },
];

export function Shell({ children }: { children: ReactNode }) {
  const { user, can, signOut } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [palette, setPalette] = useState(false);
  const location = useLocation();
  const { data: ov } = useApi(() => api.overview(), [user?.id], 4000);
  useHotkey("k", () => setPalette((p) => !p));

  const items = NAV.filter((n) => !n.need || can(n.need));
  const sections = ["Work", "Timetable", "Insight"] as const;
  const badge = (b?: NavItem["badge"]) => (b === "inbox" ? ov?.my_inbox : b === "approvals" ? ov?.pending_approvals : 0) ?? 0;

  return (
    <div className="flex h-full">
      <motion.aside
        animate={{ width: collapsed ? 76 : 264 }}
        transition={{ type: "spring", stiffness: 380, damping: 36 }}
        className="relative z-20 hidden h-full shrink-0 flex-col border-r border-line bg-panel md:flex"
      >
        <div className="flex h-16 items-center gap-3 px-5">
          <div className="grid size-9 shrink-0 place-items-center rounded-xl grad-bg shadow-lg shadow-brand/30">
            <svg viewBox="0 0 32 32" className="size-5">
              <path d="M7 22l6-12 5 8 2.5-3.5L25 22" stroke="white" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <AnimatePresence>
            {!collapsed && (
              <motion.div initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} className="min-w-0">
                <p className="truncate text-[15px] font-semibold tracking-tight">Negotiate, Then Solve</p>
                <p className="truncate text-[11.5px] text-ink-3">{ov?.department ?? "Timetabling"}</p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-3">
          {sections.map((sec) => {
            const list = items.filter((i) => i.section === sec);
            if (!list.length) return null;
            return (
              <div key={sec}>
                {!collapsed && <p className="mb-1.5 px-3 text-[11px] font-medium uppercase tracking-[0.12em] text-ink-3">{sec}</p>}
                <div className="space-y-0.5">
                  {list.map((n) => {
                    const active = n.to === "/" ? location.pathname === "/" : location.pathname.startsWith(n.to);
                    const count = badge(n.badge);
                    return (
                      <NavLink
                        key={n.to}
                        to={n.to}
                        title={collapsed ? n.label : undefined}
                        className={clsx(
                          "relative flex h-9 items-center gap-3 rounded-xl px-3 text-[13.5px] font-medium transition-colors",
                          active ? "text-ink" : "text-ink-3 hover:bg-panel-2 hover:text-ink-2",
                        )}
                      >
                        {active && (
                          <motion.span layoutId="nav-active" className="absolute inset-0 rounded-xl bg-brand/12 ring-1 ring-inset ring-brand/25" transition={{ type: "spring", stiffness: 500, damping: 40 }} />
                        )}
                        <n.icon size={17} className={clsx("relative shrink-0", active && "text-brand")} />
                        {!collapsed && <span className="relative truncate">{n.label}</span>}
                        {count > 0 && (
                          <motion.span
                            initial={{ scale: 0 }}
                            animate={{ scale: 1 }}
                            className={clsx(
                              "relative ml-auto grid min-w-5 place-items-center rounded-full bg-brand px-1.5 text-[11px] font-semibold text-white",
                              collapsed && "absolute right-1.5 top-1 ml-0 min-w-4 text-[10px]",
                            )}
                          >
                            {count}
                          </motion.span>
                        )}
                      </NavLink>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </nav>

        <div className="border-t border-line p-3">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="flex h-9 w-full items-center gap-3 rounded-xl px-3 text-[13px] text-ink-3 hover:bg-panel-2 hover:text-ink-2"
          >
            <motion.span animate={{ rotate: collapsed ? 180 : 0 }}>
              <ChevronsLeft size={17} />
            </motion.span>
            {!collapsed && "Collapse"}
          </button>
        </div>
      </motion.aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar user={user} seeding={!!ov?.seeding} onSearch={() => setPalette(true)} onSignOut={signOut} version={ov?.published_version ?? null} />
        <main className="relative flex-1 overflow-y-auto">
          <div className="pointer-events-none absolute inset-x-0 top-0 h-72 bg-gradient-to-b from-brand/[0.06] to-transparent" />
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
              className="relative mx-auto max-w-[1440px] px-4 py-7 sm:px-8"
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} items={items} />
    </div>
  );
}

function TopBar({
  user,
  seeding,
  onSearch,
  onSignOut,
  version,
}: {
  user: Persona | null;
  seeding: boolean;
  onSearch: () => void;
  onSignOut: () => void;
  version: number | null;
}) {
  const { theme, toggle } = useTheme();
  const [menu, setMenu] = useState(false);
  return (
    <header className="glass sticky top-0 z-10 flex h-16 shrink-0 items-center gap-3 border-b border-line px-4 sm:px-8">
      <button
        onClick={onSearch}
        className="flex h-9 w-full max-w-md items-center gap-2 rounded-xl border border-line bg-panel-2 px-3 text-[13px] text-ink-3 transition-colors hover:border-brand/40"
      >
        <Search size={15} />
        <span className="flex-1 text-left">Search requests, pages…</span>
        <Kbd>Ctrl K</Kbd>
      </button>
      <div className="ml-auto flex items-center gap-2">
        <div className="hidden items-center gap-2 rounded-full border border-line bg-panel-2 px-3 py-1.5 text-xs text-ink-2 lg:flex">
          <LiveDot tone={seeding ? "warn" : "ok"} />
          {seeding ? "Replaying demo history…" : "Live"}
          {version !== null && <span className="text-ink-3">· timetable v{version}</span>}
        </div>
        <button onClick={toggle} className="grid size-9 place-items-center rounded-xl text-ink-2 hover:bg-panel-2" title="Toggle theme">
          <AnimatePresence mode="wait" initial={false}>
            <motion.span key={theme} initial={{ rotate: -90, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} exit={{ rotate: 90, opacity: 0 }}>
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
            </motion.span>
          </AnimatePresence>
        </button>
        {user && (
          <div className="relative">
            <button onClick={() => setMenu(!menu)} className="flex items-center gap-2.5 rounded-xl py-1 pl-1 pr-3 hover:bg-panel-2">
              <Avatar name={user.name} id={user.id} size={30} />
              <div className="hidden text-left sm:block">
                <p className="text-[13px] font-medium leading-tight">{user.name}</p>
                <p className="text-[11px] leading-tight text-ink-3">{ROLE_LABEL[user.role]}</p>
              </div>
            </button>
            <AnimatePresence>{menu && <PersonaMenu onClose={() => setMenu(false)} onSignOut={onSignOut} />}</AnimatePresence>
          </div>
        )}
      </div>
    </header>
  );
}

function PersonaMenu({ onClose, onSignOut }: { onClose: () => void; onSignOut: () => void }) {
  const { user, signIn } = useAuth();
  const { data } = useApi(() => api.personas(), []);
  const navigate = useNavigate();
  useEffect(() => {
    const on = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest("[data-persona-menu]")) onClose();
    };
    window.addEventListener("mousedown", on);
    return () => window.removeEventListener("mousedown", on);
  }, [onClose]);
  return (
    <motion.div
      data-persona-menu
      initial={{ opacity: 0, y: -6, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -6 }}
      className="absolute right-0 top-12 w-80 overflow-hidden rounded-2xl border border-line bg-panel shadow-2xl"
    >
      <div className="border-b border-line px-4 py-3">
        <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-ink-3">
          <Users size={13} /> Switch persona (mock SSO)
        </p>
      </div>
      <div className="max-h-80 overflow-y-auto p-1.5">
        {data?.map((p) => (
          <button
            key={p.id}
            onClick={async () => {
              await signIn(p.id);
              onClose();
              navigate("/");
            }}
            className={clsx("flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left hover:bg-panel-2", p.id === user?.id && "bg-brand/10")}
          >
            <Avatar name={p.name} id={p.id} size={28} />
            <div className="min-w-0">
              <p className="truncate text-[13px] font-medium">{p.name}</p>
              <p className="truncate text-[11px] text-ink-3">{ROLE_LABEL[p.role]}</p>
            </div>
          </button>
        ))}
      </div>
      <button onClick={onSignOut} className="flex w-full items-center gap-2 border-t border-line px-4 py-3 text-[13px] text-bad hover:bg-bad/5">
        <LogOut size={15} /> Sign out
      </button>
    </motion.div>
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
      .map((c) => ({ key: c.id, label: `${c.id} · ${c.text.slice(0, 60)}`, hint: STATUS[c.status].label, icon: STATUS[c.status].icon, go: `/requests/${c.id}` }));
    return [...pages, ...cs];
  }, [q, items, cases]);

  useEffect(() => {
    setSel(0);
  }, [q, open]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-[12vh] backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
          <motion.div
            initial={{ opacity: 0, y: -12, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 420, damping: 34 }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-panel shadow-2xl"
          >
            <div className="flex items-center gap-3 border-b border-line px-4">
              <Search size={17} className="text-ink-3" />
              <input
                autoFocus
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown") setSel((s) => Math.min(results.length - 1, s + 1));
                  if (e.key === "ArrowUp") setSel((s) => Math.max(0, s - 1));
                  if (e.key === "Escape") onClose();
                  if (e.key === "Enter" && results[sel]) {
                    navigate(results[sel].go);
                    onClose();
                  }
                }}
                placeholder="Jump to a page or request…"
                className="h-14 flex-1 bg-transparent text-[15px] outline-none placeholder:text-ink-3"
              />
              <Kbd>Esc</Kbd>
            </div>
            <div className="max-h-96 overflow-y-auto p-2">
              {results.map((r, i) => (
                <button
                  key={r.key}
                  onMouseEnter={() => setSel(i)}
                  onClick={() => {
                    navigate(r.go);
                    onClose();
                  }}
                  className={clsx("flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm", i === sel ? "bg-brand/12 text-ink" : "text-ink-2")}
                >
                  <r.icon size={16} className={i === sel ? "text-brand" : "text-ink-3"} />
                  <span className="flex-1 truncate">{r.label}</span>
                  <span className="text-xs text-ink-3">{r.hint}</span>
                </button>
              ))}
              {!results.length && <p className="px-3 py-8 text-center text-sm text-ink-3">Nothing matches “{q}”.</p>}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
