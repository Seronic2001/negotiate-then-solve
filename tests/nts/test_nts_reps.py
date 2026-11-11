"""Class representatives: a section's student rep signs in, asks about the section's week, passes requests to the
office, and is told what approved changes did to the section's classes."""

from fastapi.testclient import TestClient

from nts.agents import CLASS_REP, COORDINATOR_V6, for_reps
from nts.api import Service, create_app
from nts.models import ScriptedModel, call, say
from nts.notices import notices
from nts.telemetry import MemorySink, Tracer
from nts.tools import Scope
from nts.tools.names import FULL_DAY


def app(store, steps):
    service = Service(store, ScriptedModel(steps), Tracer([MemorySink()]))
    return create_app({"demo": service}), service


def signed_in(application, name):
    c = TestClient(application)
    r = c.post("/api/login", json={"dept": "demo", "name": name, "password": ""})
    assert r.status_code == 200, r.text
    return c


def test_the_rep_agent_reads_and_ends_but_never_drafts():
    assert CLASS_REP.scopes <= {Scope.READ, Scope.POLICY, Scope.END} and Scope.END in CLASS_REP.scopes
    assert CLASS_REP.prompt.startswith(COORDINATOR_V6.prompt)  # an adapter's prompt, with the rep's rules after it
    assert for_reps(COORDINATOR_V6) == CLASS_REP


def test_a_rep_signs_in_for_a_section(store):
    g = store.world.instance.groups[1]
    a, _ = app(store, [])
    rep = signed_in(a, f"rep: {g.name}")
    assert rep.get("/api/me").json() == {"dept": "demo", "name": f"{g.name} class rep", "role": "student", "section": g.name}
    assert g.name in rep.get("/api/departments").json()["departments"][0]["sections"]
    assert TestClient(a).post("/api/login", json={"dept": "demo", "name": "rep: Section 99"}).status_code == 401


def test_a_rep_request_runs_as_the_section_and_reaches_the_office_when_passed_on(store):
    g = store.world.instance.groups[0]
    a, service = app(store, [call("classes_of", section=g.name, days=["Monday"]),
                             call("escalate", message=f"{g.name} asks to move a Monday class.")])
    rep, office, teacher = signed_in(a, f"rep: {g.name}"), signed_in(a, "office"), signed_in(a, store.world.instance.faculty[0].name)
    ep = rep.post("/api/episodes", json={"request": "Can our Monday class move? Most of us have a lab then.", "week": 5}).json()
    service.wait(ep["id"])
    done = service.get(ep["id"])
    assert done.status == "escalated" and done.actor == f"rep:{g.id}" and done.actor_name == f"{g.name} class rep"
    system = service.harness.model.seen[0][0].content
    assert f"class representative of {g.name}" in system and "14. The person asking is a class representative" in system
    tools = next(s for s in service.tracer.sinks[0].spans if s.kind == "episode").attrs["tools"]
    assert not {x["function"]["name"] for x in tools} & {"move_class", "constrain", "cancel_class"}
    assert [e["id"] for e in office.get("/api/office/requests").json()] == [ep["id"]]  # the office sees it
    assert teacher.get(f"/api/episodes/{ep['id']}").status_code == 404  # a teacher does not
    office.post(f"/api/episodes/{ep['id']}/note", json={"note": "We will look at it on Friday."})
    told = rep.get("/api/notices").json()
    assert told[0]["kind"] == "office" and told[0]["mine"] and "Friday" in told[0]["text"]


def test_an_approved_change_tells_the_sections_whose_classes_moved(store):
    inst = store.world.instance
    t = inst.faculty[1]
    day = inst.calendar.days[0]
    a, service = app(store, [call("constrain", rule="unavailable", teacher="me", days=[FULL_DAY[day]], from_week=6,
                                  to_week=6, reason="a conference"), call("check_draft"), call("submit", message="Moved.")])
    me, office = signed_in(a, t.name), signed_in(a, "office")
    ep = me.post("/api/episodes", json={"request": f"I'm away on {FULL_DAY[day]} in week 6", "week": 5}).json()
    service.wait(ep["id"])
    assert service.get(ep["id"]).status == "submitted"
    before = store.world
    assert office.post(f"/api/episodes/{ep['id']}/approve").json()["status"] == "approved"
    told = notices(before, store.world, t.id)
    moved = [k for k in told if k.startswith("rep:")]
    assert moved, "the requester's own classes moved: their sections are told"
    gid = moved[0].removeprefix("rep:")
    rep = signed_in(a, f"rep: {inst.group_by_id[gid].name}")
    lines = [n for n in rep.get("/api/notices").json() if n["kind"] == "affected"]
    assert lines and all("week 6" in n["text"] for n in lines) and any(t.name in n["text"] for n in lines)
    assert "conference" not in str(lines)  # the reason stays with the requester and the office


def test_a_reps_me_points_to_the_section_and_a_bare_number_names_one(store):
    import pytest

    from nts.tools import Refusal
    from nts.tools.names import Directory

    g = store.world.instance.groups[1]
    d = Directory(store.world.instance)
    assert d.section(g.name.split()[-1]) == g
    with pytest.raises(Refusal) as r:
        d.teacher("me", f"rep:{g.id}")
    assert r.value.error.hint == {"section": g.name}


def test_a_reps_repeated_call_is_told_to_answer_or_escalate(store):
    g = store.world.instance.groups[0]
    look = call("classes_of", section=g.name, days=["Monday"])
    a, service = app(store, [look, look, say("Monday: three classes.")])
    rep = signed_in(a, f"rep: {g.name}")
    ep = rep.post("/api/episodes", json={"request": "What do we have on Monday?", "week": 5}).json()
    service.wait(ep["id"])
    again = [e for e in service.get(ep["id"]).events if e["type"] == "tool"][1]
    assert again["result"]["code"] == "repeated_call" and "escalate" in again["result"]["message"]
    turns = [s for s in service.tracer.sinks[0].spans if s.kind == "turn" and s.trace_id == ep["id"]]
    assert set(turns[-1].attrs["offered"]) == {"decline", "escalate"}  # then it answers or passes it on
    assert all("submit" not in s.attrs["offered"] for s in turns)  # a class rep has no draft to submit
    assert service.get(ep["id"]).status == "answered"


def test_the_same_change_in_several_weeks_is_one_line():
    from nts.notices import _weeks

    assert _weeks([7, 8, 9]) == "weeks 7 to 9" and _weeks([6]) == "week 6" and _weeks([6, 8]) == "weeks 6 and 8"
    assert _weeks([None]) == "every week"


def test_a_rep_that_repeats_four_calls_in_one_turn_still_gets_to_answer(store):
    g = store.world.instance.groups[0]
    look = call("classes_of", section=g.name, days=["Monday"])
    again = look.model_copy(update={"tool_calls": [c.model_copy(update={"id": f"again-{i}"}) for i in range(4)
                                                   for c in look.tool_calls]})
    a, service = app(store, [look, again, say("Monday: three classes.")])
    rep = signed_in(a, f"rep: {g.name}")
    ep = rep.post("/api/episodes", json={"request": "What do we have on Monday?", "week": 5}).json()
    service.wait(ep["id"])
    assert service.get(ep["id"]).status == "answered"
