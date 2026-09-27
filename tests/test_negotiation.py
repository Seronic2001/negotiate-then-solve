"""Interpretation layer: ledger, priorities, explanations, the resolution
ladder and the oracle. No API calls (template explanations, scripted replies)."""

import pytest

from agents.explainer import (
    ClaimChecker,
    Explainer,
    Fact,
    OptionView,
    conflict_facts,
    leaks,
)
from agents.ledger import ConcessionLedger, gini
from agents.negotiation import Negotiator, Reply
from agents.priority import PriorityModel
from agents.simulators import Profile, Simulator, Window
from core.scenarios import uc3_lab_contention
from core.schemas import ConcessionEntry, Justification, Tier
from core.validator import verify_timetable
from evaluation.benchmark import build


def test_gini():
    assert gini([1, 1, 1, 1]) == 0
    assert gini([0, 0, 0, 4]) == pytest.approx(0.75)
    assert gini([]) == 0 and gini([0, 0]) == 0


def test_ledger_credit_decays_by_semester():
    led = ConcessionLedger([ConcessionEntry(stakeholder="F-1", constraint_id="a", semester="2025-1"),
                            ConcessionEntry(stakeholder="F-1", constraint_id="b", semester="2025-2")])
    assert led.credit("F-1", "2025-2") == pytest.approx(1.5)
    assert led.credit("F-1", "2026-1") == pytest.approx(0.75)
    led.record(ConcessionEntry(stakeholder="F-2", constraint_id="c", semester="2025-2"))  # counts 2 vs 1
    assert led.delta_gini(["F-1", "F-2"], {"F-1": 1}) > 0 > led.delta_gini(["F-1", "F-2"], {"F-2": 1})


def test_priority_prefers_verified_and_rewards_past_concessions():
    inst, cons = uc3_lab_contention()
    by_id = {c.id: c for c in cons}
    pm = PriorityModel(inst)
    verified = by_id["C-KHAN-TIME"].model_copy(update={"justification": Justification.VERIFIED})
    assert pm.score(verified) > pm.score(by_id["C-KHAN-TIME"])
    led = ConcessionLedger([ConcessionEntry(stakeholder="F-202", constraint_id="x", semester="s")])
    pm2 = PriorityModel(inst, ledger=led, semester="s")
    assert pm2.score(by_id["C-DAS-TIME"]) > pm2.score(by_id["C-KHAN-TIME"])
    assert PriorityModel(inst, flat=True).score(verified) == 1.0


def test_claim_checker_rejects_facts_not_cited():
    inst, cons = uc3_lab_contention()
    check = ClaimChecker(inst)
    fact = Fact("C-KHAN-TIME", "Dr. Khan needs the ML practical (ML-P) on Tuesday from 2 pm to 5 pm.")
    assert check.supported("Dr. Khan needs Tuesday afternoon from 2 pm.", [fact])
    assert not check.supported("Dr. Khan needs Wednesday from 2 pm.", [fact])
    assert not check.supported("Dr. Das needs Tuesday.", [fact])
    assert not check.supported("Anything at all.", [])
    assert leaks("She has a hospital visit.") == ["hospital"]


def test_facts_name_constraints_not_reasons():
    inst, cons = uc3_lab_contention()
    by_id = {c.id: c for c in cons}
    facts = conflict_facts(inst, by_id, ["C-KHAN-TIME", "C-DAS-ROOM"], [
        OptionView("A", {}, ("C-KHAN-TIME",))], {"F-202": 1})
    ids = {f.id for f in facts}
    assert {"C-KHAN-TIME", "C-DAS-ROOM", "RES-routers", "OPT-A", "LED-F-202"} <= ids
    text = Explainer(inst).explain(facts).text
    assert "Tier 4" in text and not leaks(text)


def _negotiate(profiles, ledger=None):
    inst, cons = uc3_lab_contention()
    led = ledger or ConcessionLedger()
    neg = Negotiator(inst, priority=PriorityModel(inst, ledger=led, semester="2026-1"),
                     explainer=Explainer(inst), semester="2026-1", time_limit=10)
    sims = {p.owner: Simulator(inst, p) for p in profiles}
    return inst, cons, neg.resolve(cons, sims)


def test_uc3_agreement_is_valid_and_recorded():
    past = ConcessionLedger([ConcessionEntry(stakeholder="F-202", constraint_id="old", semester="2025-2")])
    inst, cons, out = _negotiate([Profile(owner="F-201", windows=[Window(days=["Thu"], slots=[5, 6, 7])]),
                                  Profile(owner="F-202")], past)
    assert out.status == "agreed" and out.rounds == 1
    assert out.messages[0].to == "F-201"  # Dr. Das conceded last semester, so Dr. Khan is asked first
    assert len(out.messages[0].offers) == 3 and out.messages[0].faithfulness == 1.0
    ml = out.result.assignment["ML-P"]
    assert ml.day == "Thu" and ml.slot >= 5
    hard = [c for c in out.constraints if c.hard and c.tier <= Tier.OPERATIONAL]
    assert not verify_timetable(inst, out.result.assignment, hard)
    assert [e.stakeholder for e in out.concessions] == ["F-201"]


def test_counter_offer_replaces_the_constraint():
    _, _, out = _negotiate([Profile(owner="F-201", windows=[Window(days=["Fri"], slots=[0, 1, 2, 3])]),
                            Profile(owner="F-202")])
    assert out.status == "agreed" and "counter" in [r.decision for r in out.replies]
    assert out.result.assignment["ML-P"].day == "Fri"


def test_deadlock_escalates_with_a_brief():
    _, _, out = _negotiate([Profile(owner="F-201"), Profile(owner="F-202")])
    assert out.status == "escalated" and out.step == 4
    assert "deadlock" in out.escalation.reason and "Conflict:" in out.escalation.text
    assert out.result is None


def test_no_reply_escalates():
    _, _, out = _negotiate([Profile(owner="F-201", responsive=False), Profile(owner="F-202", responsive=False)])
    assert out.status == "escalated" and "no reply" in out.escalation.reason


def test_free_text_replies_need_a_parser():
    inst, cons = uc3_lab_contention()

    class Texter:
        def respond(self, message):
            return Reply(text="B works")

    neg = Negotiator(inst, priority=PriorityModel(inst), explainer=Explainer(inst), time_limit=10)
    with pytest.raises(ValueError, match="reply_parser"):
        neg.resolve(cons, {"F-201": Texter(), "F-202": Texter()})


@pytest.mark.parametrize("kind, expected", [("capacity", "escalate"), ("tradeoff", "feasible")])
def test_benchmark_kinds_and_oracle(kind, expected):
    sc = build(kind, 1, seed=3)
    assert sc.expected == expected
    neg = Negotiator(sc.instance, priority=PriorityModel(sc.instance, baseline=sc.baseline),
                     explainer=Explainer(sc.instance), time_limit=10)
    out = neg.resolve(sc.constraints, {p.owner: Simulator(sc.instance, p) for p in sc.profiles},
                      baseline=sc.baseline, week=sc.week)
    assert out.status == {"escalate": "escalated", "feasible": "feasible"}[expected]
    if kind == "capacity":
        assert out.escalation.to == "coordinator"  # Tier 0 and 2: not the owners' call
    else:
        assert out.step == 2 and out.notices  # a preference was lost: notice + appeal


def test_oracle_uses_hidden_flexibility():
    sc = build("contention", 1, seed=11)
    assert sc.oracle.status == "agree" and sc.oracle.concessions >= 1
    assert any(v != "keep" for v in sc.oracle.choice.values())
