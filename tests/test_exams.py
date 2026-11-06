"""The examination regulations as a rule (nts.exams), and both systems applying it: the request pipeline and the
agent's check_draft. The regulations come from data/policies/exam-regulations.pdf (EXAM-3.1, 3.2, 3.5)."""

import pytest

from nts.exams import exam_ruling, weeks_in

RULES = {
    "EXAM-3.1": "Mid-semester examinations are held in week 8 and end-semester examinations in week 16 of the teaching "
                "calendar. No regular classes are scheduled in these weeks.",
    "EXAM-3.2": "No change to the teaching timetable may take effect in weeks 7, 8, 15 or 16 without the written "
                "approval of the Controller of Examinations. Requests for these weeks are forwarded to the "
                "examination cell.",
    "EXAM-3.5": "Extra revision classes in week 7 or week 15 are allowed only outside the regular timetable.",
}


def test_the_weeks_come_from_the_rules_text():
    assert weeks_in(RULES["EXAM-3.2"]) == {7, 8, 15, 16}
    assert weeks_in(RULES["EXAM-3.1"]) == {8, 16}
    assert weeks_in("changes in weeks 3 and 4, or week 10") == {3, 4, 10}


@pytest.mark.parametrize(("weeks", "action", "first"), [
    ([7], "forward", "EXAM-3.2"), ([15], "forward", "EXAM-3.2"),
    ([8], "refuse", "EXAM-3.1"), ([16], "refuse", "EXAM-3.1"), ([7, 8], "refuse", "EXAM-3.1"),
])
def test_a_change_near_an_examination(weeks, action, first):
    r = exam_ruling(weeks, RULES)
    assert r is not None and r.action == action and r.cited[0] == first
    assert ("examination cell" in r.message) == (action == "forward")


def test_other_weeks_and_departments_without_the_regulations_are_left_alone():
    assert exam_ruling([6, 9, None], RULES) is None
    assert exam_ruling([], RULES) is None
    assert exam_ruling([7, 8], {"P-LUNCH": "no classes 1-2 pm"}) is None


def test_an_extra_class_cites_the_revision_rule():
    r = exam_ruling([15], RULES, extra=True)
    assert r.action == "forward" and r.cited == ["EXAM-3.2", "EXAM-3.5"] and "two hours" in r.message
    assert exam_ruling([15], RULES).cited == ["EXAM-3.2"]


@pytest.fixture(scope="module")
def world():
    from web.world import World

    return World(parser_mode="offline", seed_history=False, deadline=60)


def _ask(world, text):
    from datetime import UTC, datetime

    from core.schemas import Channel, Request, Role

    f = world.instance.faculty[0]
    r = Request(id=f"exam-{abs(hash(text))}", channel=Channel.PORTAL, sender_id=f.id, role=Role.FACULTY,
                raw_text=text, received_at=datetime.now(UTC))
    return world.orch.submit(r)


@pytest.mark.parametrize(("week", "status", "cited"), [(15, "escalated", "EXAM-3.2"), (8, "denied", "EXAM-3.1")])
def test_the_pipeline_applies_the_regulations(world, week, status, cited):
    case = _ask(world, f"I'm at a conference in week {week} on Tuesday.")
    assert "+exams" in case.route and case.status.value == status and case.policy.cited[0] == cited


def test_a_standing_change_is_not_an_examination_week_change():
    assert exam_ruling(range(5, 17), RULES) is None  # "for the rest of the semester"
    assert exam_ruling(range(1, 17), RULES) is None  # "from now on"
    assert exam_ruling([6, 7, 8], RULES).action == "refuse"  # a few weeks that take in an examination week


@pytest.mark.parametrize("text", ["I'm unavailable on Friday afternoons for the rest of the semester.",
                                  "I'm at a conference in week 6 on Tuesday."])
def test_the_pipeline_leaves_ordinary_changes_alone(world, text):
    assert "+exams" not in _ask(world, text).route
