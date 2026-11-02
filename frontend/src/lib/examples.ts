import type { InstanceView, Persona } from "./types";

/** Requests a person of this role might send, written from their own classes: a click puts one in the box. */
export function requestExamples(user: Persona | null, inst: InstanceView | null | undefined): string[] {
  if (!user || !inst) return [];
  const practical = inst.sessions.find((s) => s.faculty === user.id && s.kind === "practical");
  if (user.role === "student") return ["Machine Learning and Algorithms clash on Tuesday at 10 am for 12 of us. Can this be looked at?", "Please cancel Dr. Khan's Friday lecture, we have a quiz."];
  // the department's own rooms, so a click sends a closure the system can act on
  const labs = inst.rooms.filter((r) => r.type === "lab");
  const halls = inst.rooms.filter((r) => r.type !== "lab").sort((a, b) => b.capacity - a.capacity);
  if (user.role === "lab_incharge" && labs.length)
    return [`${labs[0].name} is closed for maintenance in weeks 11-12.`, `${labs[labs.length - 1].name} will be unavailable in week 6 while the wiring is replaced.`];
  if (user.role === "exam_cell" && halls.length)
    return [`${halls[0].name} is needed for mid-semester exams in week 8.`, `${(halls[1] ?? halls[0]).name} is closed for exams on Monday and Tuesday of week 15.`];
  if (user.role === "coordinator") return ["Who has to approve moving a class outside regular hours?"];
  return [
    "I'm at a conference in week 10, Wednesday and Thursday, so I can't take my classes then.",
    "I'd prefer no classes before 11 am on Friday, if possible.",
    practical ? `My ${practical.title} practical needs the routers; it has to be on Wednesday afternoon.` : "Please keep my Friday afternoons free.",
    "Could you schedule my lecture at 1 pm on Thursday? It's the only time that works.",
    "Is it allowed to teach more than three hours in a row?",
  ];
}
