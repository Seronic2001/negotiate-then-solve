"""Swap requests: reading them against the timetable, consent, and the flow."""

import os
from datetime import datetime

import pytest

from agents.negotiation import Reply
from agents.swap import LLMSwapReader, RuleSwapReader, _SwapDraft, looks_like_swap, swap_constraints
from core.schemas import Channel, Placement, Request, Role
from language.corpus import FULL_DAY, hour


@pytest.fixture(scope="module")
def world():
    os.environ.setdefault("NTS_RETRIEVER", "bm25")
    from web.world import World

    return World(parser_mode="offline", seed_history=False, deadline=2)


class Fixed:
    def __init__(self, decision: str) -> None:
        self.decision, self.seen = decision, []

    def respond(self, message):
        self.seen.append(message)
        return Reply(decision=self.decision, choice="A" if self.decision == "accept" else None)


def _pair(world):
    """Two lectures of different people, each the only lecture its owner has on that day."""
    inst, tt = world.instance, world.store.current_version().assignment
    lect = [s for s in inst.sessions if s.kind.value == "lecture" and s.id in tt]

    def alone(s):
        return sum(1 for x in lect if x.faculty == s.faculty and tt[x.id].day == tt[s.id].day) == 1

    a = next(s for s in lect if alone(s))
    b = next(s for s in lect if s.faculty != a.faculty and alone(s) and tt[s.id].day != tt[a.id].day)
    return a, b, tt


def _text(world, a, b, tt, weeks: str = "") -> str:
    name = world.instance.faculty_by_id[b.faculty].name
    return (f"Could I swap my {FULL_DAY[tt[a.id].day]} {hour(tt[a.id].slot)} lecture with "
            f"{name}'s {FULL_DAY[tt[b.id].day]} {hour(tt[b.id].slot)} lecture{weeks}?")


def _request(sender: str, text: str, role: Role = Role.FACULTY, rid: str = "R-T001") -> Request:
    return Request(id=rid, channel=Channel.PORTAL, sender_id=sender, role=role, raw_text=text,
                   received_at=datetime(2026, 9, 1))


def test_rule_reader_finds_both_sessions_and_weeks(world):
    a, b, tt = _pair(world)
    got = RuleSwapReader(world.instance).read(_request(a.faculty, _text(world, a, b, tt, " in weeks 4-5")), tt)
    assert got.plan is not None, got.question
    assert (got.plan.mine, got.plan.theirs, got.plan.counterpart) == (a.id, b.id, b.faculty)
    assert got.plan.weeks == [4, 5]


def test_colleague_named_first_and_pronouns(world):
    a, b, tt = _pair(world)
    name = world.instance.faculty_by_id[b.faculty].name
    text = (f"{name} and I have agreed to exchange slots: my {FULL_DAY[tt[a.id].day]} {hour(tt[a.id].slot)} "
            f"lecture for their {FULL_DAY[tt[b.id].day]} {hour(tt[b.id].slot)} lecture.")
    got = RuleSwapReader(world.instance).read(_request(a.faculty, text), tt)
    assert got.plan is not None and (got.plan.mine, got.plan.theirs) == (a.id, b.id)


def test_vague_swap_asks_instead_of_guessing(world):
    a, b, tt = _pair(world)
    name = world.instance.faculty_by_id[b.faculty].name
    got = RuleSwapReader(world.instance).read(_request(a.faculty, f"Can I swap a class with {name}?"), tt)
    assert got.plan is None and got.question


def test_ownership_is_checked_not_trusted(world):
    """A model that names someone else's session as the sender's is overruled."""
    a, b, tt = _pair(world)

    class Wrong:
        model = "stub"

        def generate(self, system, prompt, schema):
            return _SwapDraft(my_session=b.id, other_session=a.id)

    got = LLMSwapReader(world.instance, Wrong()).read(_request(a.faculty, "swap please with anyone"), tt)
    assert got.plan is None and got.refusal == "faculty can only swap their own classes"
    student = RuleSwapReader(world.instance).read(_request("ST-G-01", _text(world, a, b, tt), Role.STUDENT), tt)
    assert student.refusal


def test_session_that_would_run_past_the_day_is_not_pinned(world):
    inst, tt = world.instance, world.store.current_version().assignment
    lab = next(s for s in inst.sessions if s.duration > 1 and s.id in tt)
    last = inst.calendar.slots_per_day - 1
    other = next(s for s in inst.sessions if s.faculty != lab.faculty and s.id in tt)
    shifted = dict(tt) | {other.id: Placement(day=tt[other.id].day, slot=last, room=tt[other.id].room)}

    class Pick:
        def generate(self, system, prompt, schema):
            return _SwapDraft(my_session=lab.id, other_session=other.id)

    got = LLMSwapReader(inst, Pick()).read(_request(lab.faculty, "swap"), shifted)
    assert got.plan is None and "past the end of the day" in got.question


def test_pins_hold_each_session_at_the_others_time(world):
    a, b, tt = _pair(world)
    plan = RuleSwapReader(world.instance).read(_request(a.faculty, _text(world, a, b, tt, " in week 6")), tt).plan
    pins = swap_constraints(world.instance, plan, _request(a.faculty, "x"))
    assert {c.scope.session: (c.when.days, c.when.slots, c.owner, c.when.weeks) for c in pins} == {
        a.id: ([tt[b.id].day], [tt[b.id].slot], a.faculty, [6]),
        b.id: ([tt[a.id].day], [tt[a.id].slot], b.faculty, [6]),
    }
    assert all(c.hard for c in pins)


def test_swap_through_the_orchestrator(world):
    a, b, tt = _pair(world)
    orch = world.orch
    assert looks_like_swap(world.instance, _request(a.faculty, _text(world, a, b, tt)))

    yes = orch.responders[b.faculty] = Fixed("accept")
    case = orch.submit(world.intake.from_portal(a.faculty, _text(world, a, b, tt, " in week 3")))
    assert case.status.value == "awaiting_approval", case.reply
    assert "+swap" in case.route and yes.seen and yes.seen[0].to == b.faculty
    new = case.proposal.assignment
    assert (new[a.id].day, new[a.id].slot) == (tt[b.id].day, tt[b.id].slot)
    assert (new[b.id].day, new[b.id].slot) == (tt[a.id].day, tt[a.id].slot)
    assert case.proposal.week == 3

    orch.responders[b.faculty] = Fixed("reject")
    case = orch.submit(world.intake.from_portal(a.faculty, _text(world, a, b, tt, " in week 4")))
    assert case.status.value == "denied" and "did not agree" in case.reply
    assert not [c for c in world.store.constraints() if c.source.request == case.id]  # nothing was compiled


def test_policy_questions_about_swaps_stay_questions(world):
    r = world.intake.from_portal("F-101", "Can two faculty members swap their slots, and what does it need?")
    case = world.orch.submit(r)
    assert "+swap" not in case.route
