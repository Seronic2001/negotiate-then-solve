"""Swap requests: reading them against the timetable, and the whole flow.

    uv run python -m evaluation.swaps                       # rule reader, no API calls
    uv run python -m evaluation.swaps --reader local        # the local model (llama-server)
    uv run python -m evaluation.swaps --reader gemini       # Gemini (quota)
    uv run python -m evaluation.swaps --e2e 12              # also run swaps through the orchestrator

Requests are generated on the benchmark department's timetable (solved from
its institute rules, seeded) in several phrasings: full clues, course names
instead of times, surnames, the colleague named first, weeks or none, and
vague ones. The gold answer is exact: the clues a message states are
matched against both people's sessions, and if they fit more than one
session the right answer is a question, not a guess.

Metrics: pair accuracy on answerable requests (both sessions right), week
accuracy, how often a vague request gets a question, and wrong commitments
(a pair that is not the one meant), the error that matters most.

``--e2e N`` runs N answerable swaps through the orchestrator in the demo
department with the colleague agreeing (and N/2 declining), and checks the
proposed timetable swaps the two sessions in the weeks named.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from datetime import datetime
from pathlib import Path

from agents.swap import LLMSwapReader, RuleSwapReader
from core.instance import Instance, SessionKind, policy_constraints
from core.schemas import Channel, Placement, Request, Role
from core.solver import TimetableSolver
from language.corpus import FULL_DAY, hour
from language.rule_parser import surname

KIND = {SessionKind.LECTURE: "lecture", SessionKind.TUTORIAL: "tutorial", SessionKind.PRACTICAL: "practical"}


def _describe(inst: Instance, s, p: Placement, clues: set[str]) -> str:
    bits = []
    if "day" in clues:
        bits.append(FULL_DAY[p.day])
    if "time" in clues:
        bits.append(hour(p.slot))
    if "course" in clues:
        bits.append(inst.course_title(s.course))
    bits.append(KIND[s.kind] if "kind" in clues else "class")
    return " ".join(bits)


def _fits(inst: Instance, owner: str, s, p: Placement, clues: set[str], tt) -> list[str]:
    """Every session of ``owner`` the stated clues describe (the oracle)."""
    out = []
    for x in inst.sessions:
        q = tt.get(x.id)
        if x.faculty != owner or q is None:
            continue
        if "day" in clues and q.day != p.day:
            continue
        if "time" in clues and q.slot != p.slot:
            continue
        if "course" in clues and x.course != s.course:
            continue
        if "kind" in clues and x.kind != s.kind:
            continue
        out.append(x.id)
    return out


# weighted towards what people write (day and time), with vaguer ones mixed in
CLUE_SETS = [{"day", "time", "kind"}] * 3 + [{"day", "time", "course", "kind"}] * 2 + [{"day", "time"}] * 2 + [
    {"course", "kind"}, {"day", "kind"}, {"course"}, set()]


def generate(inst: Instance, tt: dict[str, Placement], n: int, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    placed = [s for s in inst.sessions if s.id in tt]
    rows = []
    while len(rows) < n:
        a, b = rng.sample(placed, 2)
        if a.faculty == b.faculty or (tt[a.id].day, tt[a.id].slot) == (tt[b.id].day, tt[b.id].slot):
            continue
        spd = inst.calendar.slots_per_day
        if tt[b.id].slot + a.duration > spd or tt[a.id].slot + b.duration > spd:
            continue  # would run past the end of the day; the reader says so (tested separately)
        ca, cb = rng.choice(CLUE_SETS), rng.choice(CLUE_SETS)
        fb = inst.faculty_by_id[b.faculty]
        short = rng.random() < 0.4
        name = f"Dr. {surname(fb.name)}" if short else fb.name
        namesakes = [f.id for f in inst.faculty if f.id != a.faculty and surname(f.name) == surname(fb.name)]
        w = rng.randint(2, 10)
        weeks = rng.choice([None, None, [rng.randint(2, 12)], [w, w + 1, w + 2]])
        wt = "" if weeks is None else (f" in week {weeks[0]}" if len(weeks) == 1 else f" in weeks {weeks[0]}-{weeks[-1]}")
        da, db = _describe(inst, a, tt[a.id], ca), _describe(inst, b, tt[b.id], cb)
        text = rng.choice([
            f"Could I swap my {da} with {name}'s {db}{wt}?",
            f"{name} and I have agreed to exchange slots{wt}: my {da} for their {db}.",
            f"I'd like to trade my {da} with {name}'s {db}{wt}, if that works.",
            f"Could {name} take my {da} and I take their {db}{wt}?",
            f"Hello, can we switch my {da} and {name}'s {db}{wt}? Thanks.",
        ])
        mine, theirs = _fits(inst, a.faculty, a, tt[a.id], ca, tt), _fits(inst, b.faculty, b, tt[b.id], cb, tt)
        # a surname two colleagues share does not say who is meant
        answerable = len(mine) == 1 and len(theirs) == 1 and not (short and len(namesakes) > 1)
        rows.append({"id": f"SW-{len(rows) + 1:03d}", "sender": a.faculty, "text": text, "answerable": answerable,
                     "mine": a.id, "theirs": b.id, "weeks": weeks, "clues": [sorted(ca), sorted(cb)]})
    return rows


def evaluate(inst: Instance, tt: dict[str, Placement], rows: list[dict], reader) -> dict:
    out = []
    for i, row in enumerate(rows, 1):
        r = Request(id=f"R-SW{i:03d}", channel=Channel.PORTAL, sender_id=row["sender"], role=Role.FACULTY,
                    raw_text=row["text"], received_at=datetime(2026, 9, 1))
        try:
            got = reader.read(r, tt)
        except Exception as e:  # noqa: BLE001 - an API or model failure is scored as an error
            out.append(row | {"error": f"{type(e).__name__}: {e}"})
            continue
        p = got.plan
        out.append(row | {"got": "pair" if p else ("refuse" if got.refusal else "clarify"),
                          "got_mine": p.mine if p else None, "got_theirs": p.theirs if p else None,
                          "got_weeks": p.weeks if p else None, "question": got.question})
        print(f"[{i}/{len(rows)}] {row['id']} {'answerable' if row['answerable'] else 'vague':<10} -> {out[-1].get('got')}",
              flush=True)
    ans = [x for x in out if x["answerable"] and "error" not in x]
    vague = [x for x in out if not x["answerable"] and "error" not in x]
    right = [x for x in ans if (x["got_mine"], x["got_theirs"]) == (x["mine"], x["theirs"])]
    committed = [x for x in out if x.get("got") == "pair"]
    wrong = [x for x in committed if (x["got_mine"], x["got_theirs"]) != (x["mine"], x["theirs"])]
    return {
        "n": len(rows), "answerable": len(ans), "vague": len(vague), "errors": sum("error" in x for x in out),
        "pair_accuracy": round(len(right) / len(ans), 4) if ans else None,
        "week_accuracy": round(sum(x["got_weeks"] == x["weeks"] for x in right) / len(right), 4) if right else None,
        "clarify_recall": round(sum(x["got"] == "clarify" for x in vague) / len(vague), 4) if vague else None,
        "clarify_on_answerable": round(sum(x["got"] == "clarify" for x in ans) / len(ans), 4) if ans else None,
        "wrong_commitments": len(wrong), "wrong_commitment_rate": round(len(wrong) / len(committed), 4) if committed else 0.0,
        "by_clues": dict(Counter(f"{'+'.join(x['clues'][0]) or 'none'}|{'+'.join(x['clues'][1]) or 'none'}:"
                                 f"{'ok' if x in right else x.get('got')}" for x in ans)),
        "rows": out,
    }


def e2e(n: int, seed: int = 1) -> dict:
    """Swaps through the real orchestrator in the demo department."""
    import os

    os.environ.setdefault("NTS_RETRIEVER", "bm25")
    from agents.negotiation import Reply
    from web.world import World

    class Fixed:
        def __init__(self, decision: str) -> None:
            self.decision = decision

        def respond(self, message):
            return Reply(decision=self.decision, choice="A" if self.decision == "accept" else None)

    w = World(parser_mode="offline", seed_history=False, deadline=5)
    w.autopilot_delay = 0.0
    for f in w.instance.faculty:  # anyone else the negotiation asks is answered by their simulator
        w.autopilot[f.id] = True
    tt = w.store.current_version().assignment
    rows = [r for r in generate(w.instance, tt, 4 * n, seed) if r["answerable"]][: n + n // 2]
    results = []
    for i, row in enumerate(rows):
        decision = "accept" if i < n else "reject"
        counterpart = next(s.faculty for s in w.instance.sessions if s.id == row["theirs"])
        w.orch.responders[counterpart] = Fixed(decision)
        req = w.intake.from_portal(row["sender"], row["text"])
        if req is None:
            continue
        case = w.orch.submit(req)
        ok = False
        lunch = w.instance.calendar.lunch_slot
        dur = {s.id: s.duration for s in w.instance.sessions}
        # P-SWAP: "must not break any other regulation": a move across the lunch hour is denied
        crosses_lunch = lunch is not None and any(
            at.slot <= lunch < at.slot + dur[sid]
            for sid, at in ((row["mine"], tt[row["theirs"]]), (row["theirs"], tt[row["mine"]])))
        if decision == "accept" and crosses_lunch:
            ok = case.status.value == "denied" and "P-LUNCH" in (case.policy.cited if case.policy else [])
        elif decision == "accept" and case.proposal is not None:
            a, b = case.proposal.assignment[row["mine"]], case.proposal.assignment[row["theirs"]]
            ok = ((a.day, a.slot) == (tt[row["theirs"]].day, tt[row["theirs"]].slot)
                  and (b.day, b.slot) == (tt[row["mine"]].day, tt[row["mine"]].slot)
                  and case.proposal.week == (row["weeks"][0] if row["weeks"] else None))
        elif decision == "reject":
            ok = case.status.value == "denied"
        results.append({"id": row["id"], "decision": decision, "crosses_lunch": crosses_lunch,
                        "status": case.status.value, "ok": ok, "reply": case.reply})
        print(f"[e2e {i + 1}/{len(rows)}] {decision:<6} -> {case.status.value:<18} {'OK' if ok else 'MISS'}", flush=True)
    acc = [r for r in results if r["decision"] == "accept"]
    dec = [r for r in results if r["decision"] == "reject"]
    return {"accepted": len(acc), "accepted_ok": sum(r["ok"] for r in acc), "declined": len(dec),
            "declined_ok": sum(r["ok"] for r in dec),
            "statuses": dict(Counter(f"{r['decision']}->{r['status']}" for r in results)), "rows": results}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instance", type=Path, default=Path("data/synthetic-cse-s0.json"))
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--reader", default="rules", choices=["rules", "gemini", "local"])
    ap.add_argument("--local-url", default="http://localhost:8080/v1")
    ap.add_argument("--local-model", default=None, help="model to run on a router-mode server (default NTS_LOCAL_MODEL)")
    ap.add_argument("--e2e", type=int, default=0, metavar="N", help="also run N agreed swaps through the orchestrator")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    inst = Instance.model_validate_json(args.instance.read_text(encoding="utf-8"))
    result = TimetableSolver(inst, policy_constraints(inst), time_limit=120, seed=args.seed).solve()
    if not result.ok:
        raise SystemExit(f"cannot build the timetable: {result.status}")
    tt = result.assignment
    rows = generate(inst, tt, args.n, args.seed)
    if args.reader == "rules":
        reader = RuleSwapReader(inst)
    elif args.reader == "local":
        from language.local import LocalClient

        reader = LLMSwapReader(inst, LocalClient(base_url=args.local_url, timeout=600, server_model=args.local_model))
    else:
        from language.llm import GeminiClient, default_model

        reader = LLMSwapReader(inst, GeminiClient(default_model("agent")))
    report = {"reader": args.reader, "instance": inst.name, "seed": args.seed} | evaluate(inst, tt, rows, reader)
    if args.e2e:
        report["e2e"] = e2e(args.e2e)
    summary = {k: v for k, v in report.items() if k not in ("rows", "by_clues")}
    if "e2e" in summary:
        summary["e2e"] = {k: v for k, v in report["e2e"].items() if k != "rows"}
    print("Swaps:", json.dumps(summary, indent=1))
    out = args.out or Path("runs") / f"swaps-{args.reader}-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(f"report: {out}")


if __name__ == "__main__":
    main()
