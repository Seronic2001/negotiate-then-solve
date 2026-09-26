import clsx from "clsx";
import { motion } from "framer-motion";
import { ArrowRight, Cpu, Gavel, KeyRound, Loader2, MessagesSquare, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import { Avatar, Badge } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { ROLE_LABEL } from "../lib/meta";
import type { Persona, Role } from "../lib/types";

const GROUPS: { title: string; roles: Role[] }[] = [
  { title: "Administration", roles: ["coordinator", "hod", "dean", "exam_cell"] },
  { title: "Faculty", roles: ["faculty", "guest_faculty"] },
  { title: "Operations & students", roles: ["lab_incharge", "student"] },
];

const PIPELINE = [
  { icon: Sparkles, label: "System One routes", sub: "calibrated, ~5 ms" },
  { icon: Gavel, label: "Policy agent cites rules", sub: "BM25 retrieval" },
  { icon: Cpu, label: "CP-SAT finds the conflict", sub: "MUS / MCS" },
  { icon: MessagesSquare, label: "Negotiates with people", sub: "solver-verified options" },
  { icon: ShieldCheck, label: "Human approves", sub: "nothing auto-publishes" },
];

export default function Login() {
  const { signIn } = useAuth();
  const { data, error } = useApi(() => api.personas(), []);
  const [busy, setBusy] = useState<string | null>(null);

  const go = async (p: Persona) => {
    setBusy(p.id);
    try {
      await signIn(p.id);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="grid min-h-full lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      <div className="relative hidden overflow-hidden bg-[#0b0d14] p-12 text-white lg:flex lg:flex-col">
        <div className="absolute -left-24 top-10 size-[420px] rounded-full bg-[#6d5dfc]/40 blur-[110px] animate-float" />
        <div className="absolute bottom-0 right-0 size-[380px] rounded-full bg-[#22c3ee]/25 blur-[110px] animate-float [animation-delay:-3s]" />
        <div className="absolute inset-0 bg-[linear-gradient(to_right,rgba(255,255,255,0.04)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.04)_1px,transparent_1px)] bg-[size:44px_44px] [mask-image:radial-gradient(ellipse_at_center,black,transparent_75%)]" />
        <div className="relative flex items-center gap-3">
          <div className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-[#6d5dfc] to-[#22c3ee] shadow-lg shadow-[#6d5dfc]/40">
            <svg viewBox="0 0 32 32" className="size-5">
              <path d="M7 22l6-12 5 8 2.5-3.5L25 22" stroke="white" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <span className="text-lg font-semibold tracking-tight">Negotiate, Then Solve</span>
        </div>
        <div className="relative mt-auto max-w-lg">
          <motion.h1 initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }} className="text-[44px] font-semibold leading-[1.08] tracking-tight">
            Timetable changes,
            <br />
            <span className="bg-gradient-to-r from-[#a79bff] to-[#5fdcf8] bg-clip-text text-transparent">negotiated and explained.</span>
          </motion.h1>
          <motion.p initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15, duration: 0.6 }} className="mt-5 text-[15px] leading-relaxed text-white/60">
            Requests in plain language become typed constraints. When they clash, a constraint solver finds exactly what conflicts, and the
            system negotiates only with options it has proved feasible, explaining every step.
          </motion.p>
          <div className="mt-10 space-y-2.5">
            {PIPELINE.map((p, i) => (
              <motion.div
                key={p.label}
                initial={{ opacity: 0, x: -16 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.35 + i * 0.12, duration: 0.5 }}
                className="flex items-center gap-4 rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3 backdrop-blur"
              >
                <div className="grid size-9 place-items-center rounded-xl bg-white/10">
                  <p.icon size={17} />
                </div>
                <div className="flex-1">
                  <p className="text-[14px] font-medium">{p.label}</p>
                  <p className="text-[12px] text-white/50">{p.sub}</p>
                </div>
                <motion.span
                  className="size-2 rounded-full bg-[#34d399]"
                  animate={{ opacity: [0.3, 1, 0.3] }}
                  transition={{ duration: 2, repeat: Infinity, delay: i * 0.3 }}
                />
              </motion.div>
            ))}
          </div>
        </div>
        <p className="relative mt-12 text-xs text-white/35">LMA Group Project 2026 · research prototype</p>
      </div>

      <div className="flex items-center justify-center p-6 sm:p-12">
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="w-full max-w-lg">
          <Badge tone="warn">
            <KeyRound size={12} /> Mock single sign-on
          </Badge>
          <h2 className="mt-4 text-2xl font-semibold tracking-tight">Sign in as…</h2>
          <p className="mt-1.5 text-sm text-ink-3">
            Pick a person from the college directory. In production this is the college Google Workspace / Microsoft 365 login; every permission
            below is enforced by the server.
          </p>
          {error && <p className="mt-6 rounded-xl bg-bad/10 p-4 text-sm text-bad">Cannot reach the API ({error.message}). Start it with <code>uv run nts-web</code>.</p>}
          <div className="mt-7 space-y-6">
            {GROUPS.map((g, gi) => {
              const people = (data ?? []).filter((p) => g.roles.includes(p.role));
              if (!people.length) return null;
              return (
                <div key={g.title}>
                  <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.14em] text-ink-3">{g.title}</p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {people.map((p, i) => (
                      <motion.button
                        key={p.id}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: gi * 0.08 + i * 0.03 }}
                        whileHover={{ y: -2 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => go(p)}
                        className={clsx(
                          "group flex items-center gap-3 rounded-2xl border border-line bg-panel px-3.5 py-3 text-left transition-colors hover:border-brand/50 hover:shadow-lg hover:shadow-brand/10",
                        )}
                      >
                        <Avatar name={p.name} id={p.id} size={36} />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[13.5px] font-medium">{p.name}</p>
                          <p className="truncate text-[11.5px] text-ink-3">{ROLE_LABEL[p.role]}</p>
                        </div>
                        {busy === p.id ? (
                          <Loader2 size={16} className="animate-spin text-brand" />
                        ) : (
                          <ArrowRight size={16} className="text-ink-3 opacity-0 transition-all group-hover:translate-x-0.5 group-hover:text-brand group-hover:opacity-100" />
                        )}
                      </motion.button>
                    ))}
                  </div>
                </div>
              );
            })}
            {!data && !error && (
              <div className="grid gap-2 sm:grid-cols-2">
                {Array.from({ length: 6 }, (_, i) => (
                  <div key={i} className="skeleton h-[62px] rounded-2xl" />
                ))}
              </div>
            )}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
