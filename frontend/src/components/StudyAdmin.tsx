import { Download, FlaskConical, Plus, Users } from "lucide-react";
import { useState } from "react";
import { useApi } from "../lib/hooks";
import { num, pct } from "../lib/meta";
import { study, type H3, type Kappa, type StudyAdmin as Admin } from "../lib/study";
import { Badge, Button, Card, CardHeader, Label } from "./ui";

/** The coordinator's view of the human study: codes, progress, agreement and the pilot's ratings. */
export function StudyAdmin() {
  const { data, refresh, error } = useApi(() => study.admin(), [], 5000);
  const [codes, setCodes] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const add = async (kind: "team" | "pilot") => {
    setBusy(kind);
    try {
      const got = await study.addParticipants(kind, 1);
      setCodes((c) => [...got.codes, ...c]);
      await refresh();
    } finally {
      setBusy(null);
    }
  };
  const exportAll = async () => {
    const blob = new Blob([JSON.stringify(await study.export(), null, 1)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `study-export-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <Card>
      <CardHeader
        icon={FlaskConical}
        title="Human study"
        subtitle={<>Judge validation (team) and the anonymised faculty pilot. Participants open <span className="font-mono">{window.location.origin}/study</span> and enter their code.</>}
        action={
          <div className="flex flex-wrap gap-2">
            <Button size="sm" icon={Plus} loading={busy === "team"} onClick={() => add("team")}>Team code</Button>
            <Button size="sm" icon={Plus} loading={busy === "pilot"} onClick={() => add("pilot")}>Pilot code</Button>
            <Button size="sm" variant="ghost" icon={Download} onClick={exportAll} disabled={!data?.participants.length}>Export</Button>
          </div>
        }
      />
      {error && <p className="p-5 text-[13.5px] text-bad">{error.message}</p>}
      {data && (
        <div className="space-y-6 p-5">
          {codes.length > 0 && (
            <p className="rounded-md bg-ok/10 px-3 py-2 text-[13.5px]">
              New code{codes.length > 1 ? "s" : ""}: <span className="font-mono font-semibold">{codes.join(", ")}</span>. Hand it to the participant; it is the only link to their answers.
            </p>
          )}
          {!data.items ? (
            <p className="text-[13.5px] text-ink-2">
              No study material yet. Build it from a negotiation report with explanations recorded:{" "}
              <code className="font-mono">uv run python -m evaluation.study build runs/negotiation-study-source.json</code>
            </p>
          ) : (
            <p className="text-[13px] text-ink-3">
              {data.items.claims} claims · {data.items.replies} replies · {data.items.ratings} messages ({data.items.pilot_ratings} in the pilot set) · from{" "}
              <span className="font-mono">{data.items.source}</span> · inbox replies read by {data.reply_parser}
            </p>
          )}

          <div>
            <Label>Participants</Label>
            {data.participants.length ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-[13px]">
                  <thead>
                    <tr className="border-b border-line text-left text-[12px] text-ink-3">
                      <th className="py-2 font-medium">Code</th>
                      <th className="py-2 font-medium">Group</th>
                      <th className="py-2 font-medium">Consent</th>
                      <th className="py-2 font-medium">Ratings</th>
                      <th className="py-2 font-medium">Claims</th>
                      <th className="py-2 font-medium">Replies</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.participants.map((p) => (
                      <tr key={p.code} className="border-b border-line/60">
                        <td className="py-2 font-mono">{p.code}</td>
                        <td className="py-2">{p.kind === "pilot" ? `pilot · as ${p.persona_name}` : "team"}</td>
                        <td className="py-2">{p.consented ? <Badge tone="ok">given</Badge> : <Badge>not yet</Badge>}</td>
                        {(["ratings", "claims", "replies"] as const).map((t) => (
                          <td key={t} className="py-2 font-mono text-ink-2">{p.progress[t] ? `${p.progress[t]!.done}/${p.progress[t]!.total}` : "—"}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="flex items-center gap-2 text-[13.5px] text-ink-3"><Users size={15} /> No codes issued yet. The brief plans two team raters and 5-10 pilot faculty.</p>
            )}
          </div>

          {data.analysis && <Analysis a={data.analysis} />}
        </div>
      )}
    </Card>
  );
}

function KappaList({ title, rows, note }: { title: string; rows: Record<string, Kappa>; note: string }) {
  const entries = Object.entries(rows);
  return (
    <div>
      <p className="text-[13px] font-medium">{title}</p>
      <p className="text-[12px] text-ink-3">{note}</p>
      {entries.length ? (
        <ul className="mt-1.5 space-y-1 text-[13px]">
          {entries.map(([who, k]) => (
            <li key={who} className="flex items-center gap-2">
              <span className="font-mono text-ink-2">{who}</span>
              <span className="ml-auto font-mono">κ {k.kappa === null ? "—" : num(k.kappa, 2)}</span>
              <span className="text-[12px] text-ink-3">n={k.n}</span>
              {k.kappa !== null && <Badge tone={k.kappa >= 0.6 ? "ok" : "warn"}>{k.kappa >= 0.6 ? "≥ 0.6" : "< 0.6"}</Badge>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1.5 text-[13px] text-ink-3">No labels yet.</p>
      )}
    </div>
  );
}

function H3Block({ title, h }: { title: string; h: H3 }) {
  return (
    <div>
      <p className="text-[13px] font-medium">{title}</p>
      <p className="text-[12px] text-ink-3">{h.raters} rater{h.raters === 1 ? "" : "s"}, {h.pairs} paired messages (same scenario, grounded vs free)</p>
      <table className="mt-1.5 w-full text-[13px]">
        <thead>
          <tr className="text-left text-[12px] text-ink-3">
            <th className="font-medium" />
            <th className="font-medium">Grounded</th>
            <th className="font-medium">Free</th>
            <th className="font-medium">Wilcoxon p</th>
          </tr>
        </thead>
        <tbody>
          {(["clarity", "acceptability"] as const).map((k) => (
            <tr key={k}>
              <td className="capitalize text-ink-2">{k}</td>
              <td className="font-mono">{h[k].grounded === null ? "—" : num(h[k].grounded!, 2)}</td>
              <td className="font-mono">{h[k].free === null ? "—" : num(h[k].free!, 2)}</td>
              <td className="font-mono">{h[k].wilcoxon ? num(h[k].wilcoxon!.p, 3) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Analysis({ a }: { a: NonNullable<Admin["analysis"]> }) {
  const ratingKappa = Object.fromEntries(
    Object.entries(a.ratings.kappa).flatMap(([pair, v]) => [
      [`${pair} · clarity`, { n: v.n, kappa: v.clarity ?? null }],
      [`${pair} · acceptability`, { n: v.n, kappa: v.acceptability ?? null }],
    ]),
  ) as Record<string, Kappa>;
  const u = a.live.understood;
  return (
    <div className="grid gap-6 border-t border-line pt-5 md:grid-cols-2">
      <KappaList title="Claims: human vs faithfulness verifier" rows={a.claims.human_vs_verifier} note="Cohen's κ per team rater (proposal: report only if ≥ 0.6)" />
      <KappaList title="Claims: human vs human" rows={a.claims.human_vs_human} note="Agreement between the two team raters" />
      <KappaList title="Replies: human vs recorded call" rows={a.replies.human_vs_recorded} note="What the reply does, as labelled vs as the system read it" />
      <KappaList title="Message ratings: rater vs rater" rows={ratingKappa} note="Quadratic-weighted κ; add the LLM judge with evaluation.judge" />
      <H3Block title="H3 · pilot faculty ratings" h={a.ratings.h3_pilot} />
      <H3Block title="H3 · team ratings" h={a.ratings.h3_team} />
      <div className="md:col-span-2">
        <p className="text-[13px] font-medium">Live sessions in the portal</p>
        <div className="mt-2 grid gap-4 sm:grid-cols-4">
          <Fig label="Requests checked" v={`${a.live.requests_checked}`} sub={`yes ${u.yes ?? 0} · partly ${u.partly ?? 0} · no ${u.no ?? 0}`} />
          <Fig label="Own-words replies" v={`${a.live.replies}`} sub={`reading confirmed ${pct(a.live.reply_reading_confirmed)}`} />
          <Fig label="Messages rated live" v={`${a.live.message_ratings}`} />
          <Fig label="Live clarity / acceptability" v={`${a.live.clarity === null ? "—" : num(a.live.clarity, 1)} / ${a.live.acceptability === null ? "—" : num(a.live.acceptability, 1)}`} />
        </div>
      </div>
    </div>
  );
}

function Fig({ label, v, sub }: { label: string; v: string; sub?: string }) {
  return (
    <div>
      <p className="text-[12px] text-ink-3">{label}</p>
      <p className="mt-0.5 font-serif text-xl font-semibold tabular-nums">{v}</p>
      {sub && <p className="text-[12px] text-ink-3">{sub}</p>}
    </div>
  );
}
