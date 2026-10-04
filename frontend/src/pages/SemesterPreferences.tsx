import clsx from "clsx";
import { SlidersHorizontal, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { OfferingsCatalog } from "../components/OfferingsCatalog";
import { Badge, Button, Card, CardHeader, EmptyState, Label, PageHeader } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { mentionInto } from "../lib/mention";
import type { ParsedInput } from "../lib/types";

export default function SemesterPreferences() {
  const { user } = useAuth();
  const { data: pub } = useApi(() => api.semesterPublic(), []);
  const { data: mine, refresh } = useApi(() => api.myPreferences(), []);
  const [text, setText] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);
  const [preview, setPreview] = useState<ParsedInput | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const student = user?.role === "student";
  // examples name people, courses and groups that are really in the loaded offering document
  const cat = pub?.catalog ?? [];
  const teachers = [...new Set(cat.flatMap((c) => c.faculty))];
  const groups = pub?.cohorts.map((c) => c.name) ?? [];
  // a teacher's examples are about themselves and their courses, a class rep's about their section
  const mineCourses = cat.filter((c) => user && c.faculty.includes(user.name));
  const mySection = student && user ? pub?.cohorts.find((c) => c.id === user.id.replace(/^ST-/, ""))?.name : undefined;
  const examples = student
    ? [`${mySection ?? groups[0] ?? "Section 1"} students would like no classes after 4 pm on Friday`, `${mySection ?? groups[0] ?? "Section 1"} wants Tuesday afternoons free`]
    : mineCourses.length && user
      ? [
          `${user.name} prefers not to teach before 10 am`,
          `${user.name} is unavailable on Fridays`,
          `${mineCourses[0].code} should be in the morning`,
        ]
      : [
          `${teachers[0] ?? "Dr. Menon"} prefers not to teach before 10 am`,
          `${teachers[1] ?? teachers[0] ?? "Dr. Iyer"} is unavailable on Fridays`,
          `${cat[0]?.code ?? "CS1.101"} should be in the morning`,
        ];

  const check = async (t: string) => {
    setText(t);
    setError(null);
    try {
      setPreview(t.trim() ? await api.addPreference(t, true) : null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (pub && !pub.loaded)
    return (
      <>
        <PageHeader title="Semester preferences" />
        <EmptyState icon={SlidersHorizontal} title="The next semester's offerings are not loaded yet" text="The timetable office loads them first; then you can add preferences here." />
      </>
    );

  /** A course, teacher or group picked from the catalogue goes into the text, and the preview updates. */
  const mention = (name: string) => mentionInto(box.current, text, name, (t) => void check(t));

  return (
    <div className="grid max-w-6xl gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0">
        <PageHeader
          title="Semester preferences"
          subtitle={
            student
              ? "Tell the timetable office what would help your programme. They are weighed when the semester timetable is built."
              : "When you would rather not teach, or cannot. The timetable office builds the semester with these."
          }
        />
        <Card className="mb-6 p-5">
          <textarea
            ref={box}
            value={text}
            onChange={(e) => void check(e.target.value)}
            rows={3}
            placeholder={examples[0]}
            className="w-full resize-none rounded-md border border-line bg-panel p-3 text-[14px] outline-none focus:border-brand/60"
          />
          {preview && <p className={clsx("mt-2 text-[13px]", preview.ok ? "text-ink-2" : "text-warn")}>{preview.ok ? `Understood: ${preview.summary?.join("; ")}` : preview.error}</p>}
          {error && <p className="mt-2 text-[13px] text-bad">{error}</p>}
          <div className="mt-3 flex items-center gap-3">
            <Button
              variant="primary"
              disabled={!preview?.ok}
              loading={busy}
              onClick={async () => {
                setBusy(true);
                await api.addPreference(text);
                setText("");
                setPreview(null);
                setBusy(false);
                await refresh();
              }}
            >
              Send
            </Button>
            <span className="text-[12px] text-ink-3">Name the {student ? "programme and year" : "faculty member or course"}, and say when.</span>
          </div>
          <Label className="mt-5">Examples</Label>
          {examples.map((e) => (
            <button key={e} onClick={() => void check(e)} className="block text-left text-[13px] text-ink-2 hover:text-brand">
              “{e}”
            </button>
          ))}
        </Card>
        <Card>
          <CardHeader title="Sent" />
          <ul className="divide-y divide-line">
            {(mine ?? []).map((p) => (
              <li key={p.id} className="flex items-center gap-3 px-5 py-3">
                <p className="min-w-0 flex-1 text-[13.5px]">{p.text}</p>
                <Badge tone={p.hard ? "bad" : "muted"}>{p.hard ? "cannot" : "preference"}</Badge>
                <button
                  onClick={async () => {
                    await api.removePreference(p.id);
                    await refresh();
                  }}
                  className="grid size-7 place-items-center rounded-md text-ink-3 hover:bg-panel-2 hover:text-bad"
                  title="Withdraw"
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
            {!mine?.length && <li className="px-5 py-8 text-center text-[13px] text-ink-3">Nothing sent yet.</li>}
          </ul>
        </Card>
      </div>
      {pub?.loaded && (
        <aside className="lg:pt-[72px]">
          <OfferingsCatalog overview={pub} onPick={mention} />
        </aside>
      )}
    </div>
  );
}
