import { ArrowRight, Loader2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Avatar, Label, Mark } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { ROLE_LABEL } from "../lib/meta";
import type { Persona, Role } from "../lib/types";

const GROUPS: { title: string; roles: Role[] }[] = [
  { title: "Administration", roles: ["coordinator", "hod", "dean", "exam_cell"] },
  { title: "Faculty", roles: ["faculty", "guest_faculty"] },
  { title: "Operations and students", roles: ["lab_incharge", "student"] },
];

const STEPS = [
  ["Write a request in plain language.", "It becomes typed constraints; the handbook is checked and the rule cited."],
  ["The solver finds what clashes.", "Only the smallest set of conflicting constraints, never a guess."],
  ["The office asks the right person.", "With two or three options the solver has already proved work."],
  ["A person approves before anything is published.", "Everyone affected, and only them, is told."],
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
    <div className="grid min-h-full lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      {/* pinned to the viewport: a large department's persona list makes the page much taller than the screen */}
      <div className="hidden border-r border-line bg-panel p-12 lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col lg:self-start">
        <div className="flex items-center gap-2.5">
          <Mark size={26} />
          <span className="font-serif text-[17px] font-semibold">Negotiate, Then Solve</span>
        </div>
        <div className="my-auto max-w-md">
          <h1 className="font-serif text-[38px] leading-[1.15] font-semibold">Timetable changes, negotiated and explained.</h1>
          <ol className="mt-10 space-y-5">
            {STEPS.map(([head, text], i) => (
              <li key={head} className="flex gap-4">
                <span className="font-serif text-[20px] leading-none text-brand">{i + 1}</span>
                <div>
                  <p className="text-[14.5px] font-medium">{head}</p>
                  <p className="mt-0.5 text-[13.5px] text-ink-3">{text}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
        <p className="text-[12px] text-ink-3">LMA Group Project 2026 · research prototype</p>
      </div>

      <div className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-md">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <Mark size={24} />
            <span className="font-serif text-[16px] font-semibold">Negotiate, Then Solve</span>
          </div>
          <h2 className="font-serif text-[26px] font-semibold">Sign in</h2>
          <p className="mt-1 text-[13.5px] text-ink-3">Demo sign-in: choose who you are. The college login replaces this in production.</p>
          <Link to="/study" className="mt-3 inline-flex items-center gap-1.5 text-[13.5px] font-medium text-brand hover:underline">
            Taking part in the study? Enter your code <ArrowRight size={14} />
          </Link>
          {error && (
            <p className="mt-6 rounded-md border border-bad/30 p-4 text-[13.5px] text-bad">
              Cannot reach the server ({error.message}). Start it with <code className="font-mono">uv run nts-web</code>.
            </p>
          )}
          <div className="mt-8 space-y-6">
            {GROUPS.map((g) => {
              const people = (data ?? []).filter((p) => g.roles.includes(p.role));
              if (!people.length) return null;
              return (
                <div key={g.title}>
                  <Label>{g.title}</Label>
                  <div className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-panel">
                    {people.map((p) => (
                      <button key={p.id} onClick={() => go(p)} className="group flex w-full items-center gap-3 px-3.5 py-2.5 text-left hover:bg-panel-2/60">
                        <Avatar name={p.name} id={p.id} size={30} />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[13.5px] font-medium">{p.name}</p>
                          <p className="truncate text-[12px] text-ink-3">{ROLE_LABEL[p.role]}</p>
                        </div>
                        {busy === p.id ? (
                          <Loader2 size={15} className="animate-spin text-ink-3" />
                        ) : (
                          <ArrowRight size={15} className="text-ink-3 opacity-0 transition-opacity group-hover:opacity-100" />
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
            {!data && !error && <div className="skeleton h-64 rounded-lg" />}
          </div>
        </div>
      </div>
    </div>
  );
}
