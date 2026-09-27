"""Negotiation experiments (RQ1, RQ2): our system against baselines B1-B4
and ablations A1-A3 on the 60 scenarios.

    uv run python -m evaluation.negotiation --offline          # no API calls
    uv run python -m evaluation.negotiation --configs ours-llm,A1,A3,B1,B3
    uv run python -m evaluation.negotiation --configs ours-llm,A3 --local   # agent on llama-server

Configurations:

* ``ours``      MCS options, tiers + ledger, template explanations, scripted replies (offline)
* ``ours-llm``  the same with grounded LLM explanations; simulators write replies
                with Flash-Lite and System Two parses them
* ``A1``        options invented by the LLM instead of MCS
* ``A2``        flat weights, no ledger
* ``A3``        free LLM explanations instead of grounded ones
* ``B1``        LLM-only: the LLM writes the timetable directly
* ``B2``        solver with flat weights, result imposed without asking
* ``B3``        free LLM negotiation: invented options, flat weights, no ledger
* ``B4``        the oracle (computed with the scenario; hidden flexibility known)

Scenarios run in order with one concession ledger per configuration, so the
concession Gini (H1d) reflects a semester of conflicts among the same four
faculty IDs.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from agents.explainer import Explainer, describe
from agents.ledger import ConcessionLedger
from agents.negotiation import Negotiator, ReplyParser
from agents.priority import PriorityModel
from agents.simulators import Simulator
from core.schemas import Placement, Tier
from core.solver import TimetableSolver
from core.validator import verify_timetable
from language.llm import GeminiClient, default_model

from .benchmark import Scenario, load
from .stats import bootstrap_ci, mcnemar, mean, wilcoxon

SEMESTER = "2026-1"
STAKEHOLDERS = ["F-301", "F-302", "F-303", "F-304"]
OFFLINE = ["ours", "A2", "B2", "B4"]
LLM = ["ours-llm", "A1", "A3", "B1", "B3"]

CONFIGS = {
    # option_source, flat priorities, use ledger, explanation mode, LLM replies
    "ours": ("mcs", False, True, "template", False),
    "ours-llm": ("mcs", False, True, "grounded", True),
    "A1": ("llm", False, True, "grounded", True),
    "A2": ("mcs", True, False, "template", False),
    "A3": ("mcs", False, True, "free", True),
    "B3": ("llm", True, False, "free", True),
}


class _Timetable(BaseModel):
    class Item(BaseModel):
        session: str
        day: str
        slot: int
        room: str

    placements: list[Item]


B1_PROMPT = """You are a university timetabler. Place every session: choose a day, a start
slot and a room. Rules: a room, a faculty member or a section can hold one
session at a time; a session of duration d occupies d consecutive slots on
one day; labs need lab rooms with the equipment listed; respect every
constraint listed as far as possible. Output every session exactly once."""


def validity(sc: Scenario, assignment: dict[str, Placement] | None, extra=()) -> bool:
    """Hard-constraint validity (H1a): physical rules plus every Tier 0-2
    constraint, and any constraints the system itself claims to enforce."""
    if not assignment:
        return False
    must = [c for c in sc.constraints if c.hard and c.tier <= Tier.COMMITMENT] + list(extra)
    return not verify_timetable(sc.instance, assignment, must, week=sc.week)


def _moved(sc: Scenario, assignment) -> int:
    return sum(1 for s, p in sc.baseline.items() if assignment and assignment.get(s) != p)


def run_negotiation(sc: Scenario, config: str, shared: ConcessionLedger, agent, sim) -> dict:
    source, flat, use_ledger, mode, llm_replies = CONFIGS[config]
    ledger = ConcessionLedger([*shared.entries, *sc.ledger])
    pm = PriorityModel(sc.instance, ledger=ledger, semester=SEMESTER, baseline=sc.baseline, flat=flat)
    explainer = Explainer(sc.instance, mode=mode, client=agent if mode != "template" else None)
    neg = Negotiator(sc.instance, priority=pm, explainer=explainer, ledger=ledger, semester=SEMESTER,
                     reply_parser=ReplyParser(agent, sc.instance) if llm_replies else None,
                     option_source=source, option_client=agent, use_ledger=use_ledger, time_limit=20)
    sims = {p.owner: Simulator(sc.instance, p, client=sim if llm_replies else None, structured=not llm_replies)
            for p in sc.profiles}
    out = neg.resolve(sc.constraints, sims, baseline=sc.baseline, week=sc.week, private=sc.private,
                      raw_requests=sc.raw_requests)
    shared.entries.extend(out.concessions)
    assignment = out.result.assignment if out.result and out.result.ok else None
    agreed = [c for c in out.constraints if c.hard]
    conceders = {c.stakeholder for c in out.concessions}
    return {
        "status": out.status,
        "rounds": out.rounds,
        "valid": validity(sc, assignment, agreed) if assignment else None,
        "moved": _moved(sc, assignment) if assignment else None,
        "concessions": len(conceders),
        "conceders": sorted(conceders),
        "escalated_to": out.escalation.to if out.escalation else None,
        "faithfulness": mean([m.faithfulness for m in out.messages]),
        "leaks": sum(len(m.leaks) for m in out.messages),
        "rejected_claims": sum(m.rejected_claims for m in out.messages),
        "explanation_modes": dict(Counter(m.explanation_mode for m in out.messages)),
        "first_accepted": bool(out.replies) and out.replies[0].decision == "accept",
        "messages": [m.text for m in out.messages],
        "replies": [r.model_dump(exclude_none=True) for r in out.replies],
    }


def run_imposed(sc: Scenario) -> dict:
    """B2: planted request constraints become equal-weight preferences; the
    solver's answer is imposed. Owners are not asked; we record whether each
    imposed change would have been acceptable to them."""
    cons = []
    for c in sc.constraints:
        if c.hard and c.tier > Tier.COMMITMENT and c.type.value in ("prefer", "avoid", "require_room"):
            cons.append(c.model_copy(update={"hard": False, "tier": Tier.PREFERENCE, "weight": 1.0}))
        else:
            cons.append(c)
    r = TimetableSolver(sc.instance, cons, week=sc.week, baseline=sc.baseline, time_limit=20).solve()
    if not r.ok:
        return {"status": "failed", "rounds": 0, "valid": None, "moved": None, "concessions": 0}
    losers = {sc_c.owner for sc_c in sc.planted if sc_c.id in r.soft_violations and sc_c.owner}
    sims = {p.owner: Simulator(sc.instance, p) for p in sc.profiles}
    acceptable = []
    for owner in losers:
        sim = sims.get(owner)
        own = {s.id for c in sc.planted if c.owner == owner
               for s in sc.instance.sessions if c.scope.session == s.id or c.scope.faculty == s.faculty}
        acceptable.append(bool(sim) and all(sim.acceptable(s, r.assignment[s]) for s in own if s in r.assignment))
    return {"status": "imposed" if losers else "feasible", "rounds": 0, "valid": validity(sc, r.assignment),
            "moved": _moved(sc, r.assignment), "concessions": len(losers),
            "imposed_acceptable": mean(acceptable) if acceptable else None}


def run_llm_only(sc: Scenario, agent) -> dict:
    inst = sc.instance
    sessions = "\n".join(
        f"{s.id}: faculty {s.faculty}, sections {','.join(s.groups)}, duration {s.duration}, "
        f"{'lab' if s.room_type.value == 'lab' else 'lecture room'}"
        + (f", needs {','.join(s.equipment)}" if s.equipment else "") for s in inst.sessions)
    rooms = "\n".join(f"{r.id}: {r.type.value}" + (f", equipment {','.join(r.equipment)}" if r.equipment else "")
                      for r in inst.rooms)
    cons = "\n".join(f"- {describe(inst, c)}" for c in sc.constraints if c.active_in(sc.week))
    prompt = (f"Days: {', '.join(inst.calendar.days)}; slots 0-{inst.calendar.slots_per_day - 1} "
              f"(slot 4 is lunch).\n\nRooms:\n{rooms}\n\nSessions:\n{sessions}\n\nConstraints:\n{cons}")
    got = agent.generate(B1_PROMPT, prompt, _Timetable)
    assignment = {p.session: Placement(day=p.day, slot=p.slot, room=p.room) for p in got.placements}
    problems = verify_timetable(inst, assignment, [c for c in sc.constraints if c.hard], week=sc.week)
    return {"status": "llm_timetable", "rounds": 0, "valid": validity(sc, assignment),
            "all_hard_ok": not problems, "moved": _moved(sc, assignment), "concessions": 0,
            "problems": problems[:5]}


def run_oracle(sc: Scenario) -> dict:
    o = sc.oracle
    return {"status": {"agree": "agreed", "escalate": "escalated"}.get(o.status, o.status), "rounds": 0,
            "valid": o.status != "escalate" or None, "moved": o.moved, "concessions": o.concessions}


def correct_outcome(row: dict, sc: Scenario) -> bool:
    want = {"feasible": {"feasible"}, "agree": {"agreed"}, "escalate": {"escalated", "failed"}}[sc.expected]
    return row["status"] in want


def summarise(rows: list[dict], scenarios: dict[str, Scenario], ledger: ConcessionLedger | None) -> dict:
    by_id = {r["scenario"]: r for r in rows}
    need_agree = [r for r in rows if scenarios[r["scenario"]].expected == "agree"]
    agreed = [r for r in need_agree if r["status"] == "agreed" and r.get("moved") is not None]
    ratio = []
    for r in agreed:
        o = scenarios[r["scenario"]].oracle
        ours = r["moved"] + r["concessions"]
        ratio.append(ours / o.cost if o.cost else (1.0 if ours == 0 else 2.0))
    escalate_gold = [scenarios[s].expected == "escalate" for s in by_id]
    escalate_pred = [by_id[s]["status"] in ("escalated", "failed") for s in by_id]
    tp = sum(g and p for g, p in zip(escalate_gold, escalate_pred, strict=True))
    produced = [r["valid"] for r in rows if r.get("valid") is not None]
    return {
        "n": len(rows),
        "correct_outcome": mean([correct_outcome(r, scenarios[r["scenario"]]) for r in rows]),
        "validity_of_timetables": mean(produced),
        "timetables_produced": len(produced),
        "agreement_rate": mean([r["status"] == "agreed" for r in need_agree]),
        "rounds_mean": mean([r["rounds"] for r in need_agree]),
        "rounds_ci": bootstrap_ci([r["rounds"] for r in need_agree]),
        "cost_ratio_to_oracle": mean(ratio),
        "within_10pct_of_oracle": mean([x <= 1.1 for x in ratio]),
        "escalation_precision": tp / sum(escalate_pred) if sum(escalate_pred) else None,
        "escalation_recall": tp / sum(escalate_gold) if sum(escalate_gold) else None,
        "concession_gini": ledger.gini(STAKEHOLDERS, SEMESTER) if ledger else None,
        "first_proposal_acceptance": mean([r.get("first_accepted") for r in rows if r.get("rounds")]),
        "explanation_faithfulness": mean([r.get("faithfulness") for r in rows]),
        "private_leaks": sum(r.get("leaks", 0) for r in rows),
        "explanation_modes": dict(sum((Counter(r.get("explanation_modes", {})) for r in rows), Counter())),
        "imposed_acceptable": mean([r.get("imposed_acceptable") for r in rows]),
        "status": dict(Counter(r["status"] for r in rows)),
        "wall_s": sum(r["wall_s"] for r in rows),
    }


def compare(a: list[dict], b: list[dict], scenarios) -> dict:
    """Paired tests of configuration a against b on the same scenarios."""
    ka, kb = {r["scenario"]: r for r in a}, {r["scenario"]: r for r in b}
    ids = [s for s in ka if s in kb]
    ok_a = [correct_outcome(ka[s], scenarios[s]) for s in ids]
    ok_b = [correct_outcome(kb[s], scenarios[s]) for s in ids]
    agree = [s for s in ids if scenarios[s].expected == "agree"]
    return {"correct_outcome_mcnemar": mcnemar(ok_a, ok_b),
            "rounds_wilcoxon": wilcoxon([ka[s]["rounds"] for s in agree], [kb[s]["rounds"] for s in agree])}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios", type=Path, default=Path("data/scenarios.jsonl"))
    ap.add_argument("--configs", default=None, help="comma-separated; default: all offline configs")
    ap.add_argument("--offline", action="store_true", help="only configurations that need no API")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", default=None, help="comma-separated scenario ids")
    ap.add_argument("--agent-model", default=None,
                    help="model for explanations, reply parsing, invented options and B1 (default: agent model); "
                         "use the simulator model for development when the agent quota is spent")
    ap.add_argument("--local", action="store_true",
                    help="run the agent (explanations, reply parsing, invented options, B1) on the local "
                         "model behind an OpenAI-compatible server instead of Gemini")
    ap.add_argument("--sim-local", action="store_true", help="run the stakeholder simulators locally too")
    ap.add_argument("--local-url", default="http://localhost:8080/v1")
    ap.add_argument("--local-max-tokens", type=int, default=2048)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    scenarios = load(args.scenarios)
    if args.only:
        wanted = set(args.only.split(","))
        scenarios = [s for s in scenarios if s.id in wanted]
    scenarios = scenarios[: args.limit]
    by_id = {s.id: s for s in scenarios}
    configs = args.configs.split(",") if args.configs else OFFLINE
    if args.offline:
        configs = [c for c in configs if c in OFFLINE]
    agent = sim = None
    if any(c in LLM for c in configs):
        local = None
        if args.local or args.sim_local:
            from language.local import LocalClient

            local = LocalClient(base_url=args.local_url, max_tokens=args.local_max_tokens, timeout=600)
        agent = local if args.local else GeminiClient(args.agent_model or default_model("agent"))
        sim = local if args.sim_local else GeminiClient(default_model("simulator"))

    report: dict = {"scenarios": str(args.scenarios), "configs": {},
                    "models": {"agent": getattr(agent, "model", None), "simulator": getattr(sim, "model", None)}}
    all_rows: dict[str, list[dict]] = {}
    for config in configs:
        shared = ConcessionLedger()
        rows = []
        for sc in scenarios:
            t = time.perf_counter()
            if config == "B1":
                row = run_llm_only(sc, agent)
            elif config == "B2":
                row = run_imposed(sc)
            elif config == "B4":
                row = run_oracle(sc)
            else:
                row = run_negotiation(sc, config, shared, agent, sim)
            row.update(scenario=sc.id, kind=sc.kind, expected=sc.expected, wall_s=time.perf_counter() - t)
            rows.append(row)
            print(f"[{config}] {sc.id} expected={sc.expected} got={row['status']} rounds={row['rounds']} "
                  f"valid={row.get('valid')}", flush=True)
        all_rows[config] = rows
        uses_ledger = config in CONFIGS
        report["configs"][config] = {"summary": summarise(rows, by_id, shared if uses_ledger else None),
                                     "rows": rows}
    if "ours" in all_rows or "ours-llm" in all_rows:
        ref = "ours-llm" if "ours-llm" in all_rows else "ours"
        report["paired"] = {f"{ref} vs {c}": compare(all_rows[ref], all_rows[c], by_id)
                            for c in all_rows if c != ref}
    for c, v in report["configs"].items():
        print(f"\n== {c}\n" + json.dumps(v["summary"], indent=1, default=str))
    if "paired" in report:
        print("\npaired:", json.dumps(report["paired"], indent=1))
    out = args.out or Path("runs") / f"negotiation-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(f"report: {out}")


if __name__ == "__main__":
    main()
