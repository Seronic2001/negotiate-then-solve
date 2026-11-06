"""The agentic demo (web.agentic): the chat is the agent loop, the rest of the app is the demo's. A scripted model
plays the agent, so every test is deterministic and needs no server."""

import time

import pytest
from fastapi.testclient import TestClient

from nts.models import ScriptedModel, call, say
from nts.telemetry import MemorySink, Tracer
from nts.tools.names import FULL_DAY
from web import agentic
from web.app import World, create_web_app
from web.world import COORDINATOR


class Playbook:
    """The model the desk talks to; each test loads its own script."""

    name = "scripted"

    def __init__(self) -> None:
        self.model = ScriptedModel([])

    def load(self, steps) -> None:
        self.model = ScriptedModel(steps)

    def chat(self, messages, tools):
        return self.model.chat(messages, tools)


@pytest.fixture(scope="module")
def demo():
    world = World(parser_mode="offline", seed_history=False, deadline=60)
    play = Playbook()
    desk = agentic.AgentDesk(world, play, tracer=Tracer([MemorySink()]), picker=False, ticker=False)
    agentic._desks[world] = desk
    return TestClient(create_web_app(world)), world, desk, play


def teacher(world, n=0):
    return world.instance.faculty[n].id


def send(c, person, text):
    r = c.post("/api/chat", json={"text": text}, headers={"X-User": person})
    assert r.status_code == 200, r.text
    return r.json()


def settled(c, desk, person):
    """The chat once the agent has stopped working (and the cases are in line with it)."""
    for ep in list(desk.svc.episodes.values()):
        desk.svc.wait(ep.id, timeout=60)
    desk.sync()
    return c.get("/api/chat", headers={"X-User": person}).json()


def test_a_question_is_answered_in_the_chat_and_is_no_request(demo):
    c, world, desk, play = demo
    me = teacher(world, 0)
    play.load([call("describe", what="rooms"), say("There are several rooms; Lab 1 is a lab.")])
    before = len(world.store.requests())
    mine, reply = send(c, me, "Which rooms are there?")
    assert (mine["kind"], reply["kind"]) == ("text", "agent") and reply["episode"]
    last = settled(c, desk, me)[-1]
    assert last["status"] == "answered" and last["text"].startswith("There are several rooms")
    assert [s["type"] for s in last["steps"]][:2] == ["model", "tool"] and last["steps"][1]["name"] == "describe"
    assert last["case"] is None and len(world.store.requests()) == before


def test_a_question_back_is_answered_with_the_next_message(demo):
    c, world, desk, play = demo
    me = teacher(world, 1)
    play.load([call("ask_requester", question="Which class do you mean?"), say("Thanks, that is clear now.")])
    send(c, me, "Move my class please")
    asked = settled(c, desk, me)[-1]
    assert asked["status"] == "waiting" and asked["pending"]["to_requester"]
    assert asked["pending"]["text"] == "Which class do you mean?"
    _, more = send(c, me, "My Monday lecture.")
    assert more["episode"] == asked["episode"] and more["from"] > 0  # the same episode goes on
    chat = settled(c, desk, me)
    first, last = (m for m in chat if m["kind"] == "agent" and m["episode"] == asked["episode"])
    assert first["status"] == "answered_later" and first["pending"] is None
    assert last["status"] == "answered" and last["text"] == "Thanks, that is clear now."
    assert any(s["type"] == "reply" and s["says"] == "My Monday lecture." for s in last["steps"])


def test_a_change_goes_to_the_office_and_is_published_in_the_demo(demo):
    c, world, desk, play = demo
    me = teacher(world, 2)
    week = (world.current_week() or 1) + 1
    day = world.instance.calendar.days[0]
    play.load([call("constrain", rule="unavailable", teacher="me", days=[FULL_DAY[day]], from_week=week, to_week=week,
                    reason="a conference"),
               call("check_draft"), call("submit", message="Your classes that day move.")])
    send(c, me, f"I am at a conference on {FULL_DAY[day]} in week {week}")
    msg = settled(c, desk, me)[-1]
    assert msg["status"] == "submitted" and msg["case"] and any("not available" in d for d in msg["draft"])
    cid = msg["case"]
    mine = c.get("/api/cases?scope=mine", headers={"X-User": me}).json()
    assert [(x["id"], x["status"], x["route"]) for x in mine if x["id"] == cid] == [(cid, "awaiting_approval", "agent")]
    pending = c.get("/api/approvals", headers={"X-User": COORDINATOR}).json()
    case = next(p for p in pending if p["id"] == cid)
    assert case["proposal"] and case["proposal"]["week"] == week and case["understood"]
    assert c.get(f"/api/cases/{cid}", headers={"X-User": COORDINATOR}).json()["agent"]["status"] == "submitted"

    assert c.post(f"/api/approvals/{cid}/approve", headers={"X-User": me}).status_code == 403
    r = c.post(f"/api/approvals/{cid}/approve", headers={"X-User": COORDINATOR})
    assert r.status_code == 200, r.text
    version = r.json()["version"]
    assert version and world.store.current_version(week).version == version  # in the demo's own timetable
    assert any(x.source.request == cid for x in world.store.constraints())  # its rule, in force
    assert world.orch.cases[cid].status.value == "published"
    assert desk._mark() == desk.synced  # the agent's mirror already has it
    events = [e["kind"] for e in world.store.events(cid)]
    assert events[0] == "received" and "awaiting_approval" in events and events[-1] == "published"
    assert settled(c, desk, me)[-1]["case_status"] == "published"


def test_a_change_made_elsewhere_reaches_the_agent_before_its_next_message(demo):
    c, world, desk, play = demo
    me = teacher(world, 3)
    sem = world.store.current_version()
    v = world.store.propose_version(dict(sem.assignment), "elsewhere", week=9)
    world.store.publish_version(v.version, COORDINATOR)
    assert desk._mark() != desk.synced
    play.load([say("Noted.")])
    send(c, me, "hello")
    settled(c, desk, me)
    assert desk._mark() == desk.synced and 9 in desk.svc.store.world.timetables


def test_the_office_rejects_and_the_sender_hears_why(demo):
    c, world, desk, play = demo
    me = teacher(world, 4)
    week = (world.current_week() or 1) + 2
    day = world.instance.calendar.days[1]
    play.load([call("constrain", rule="unavailable", teacher="me", days=[FULL_DAY[day]], from_week=week, to_week=week,
                    reason="a workshop"),
               call("check_draft"), call("submit", message="Your classes that day move.")])
    send(c, me, f"away on {FULL_DAY[day]} week {week}")
    cid = settled(c, desk, me)[-1]["case"]
    r = c.post(f"/api/approvals/{cid}/reject", json={"reason": "exams that week"}, headers={"X-User": COORDINATOR})
    assert r.status_code == 200 and r.json()["status"] == "denied"
    detail = c.get(f"/api/cases/{cid}", headers={"X-User": me}).json()
    assert detail["reply"] == "The timetable office did not approve this: exams that week."


def test_a_request_passed_to_the_office_is_answered_by_it(demo):
    c, world, desk, play = demo
    me = teacher(world, 5)
    play.load([call("escalate", message="Asks for a projector in every room; only the office can buy one."),
               say("I have passed this to the timetable office.")])
    send(c, me, "Please put a projector in every room")
    msg = settled(c, desk, me)[-1]
    cid = msg["case"]
    assert msg["status"] == "escalated" and world.orch.cases[cid].status.value == "forwarded"
    detail = c.get(f"/api/cases/{cid}", headers={"X-User": COORDINATOR}).json()
    assert detail["can_handle"] and detail["forwarded_to"] == "coordinator"
    r = c.post(f"/api/cases/{cid}/handle", json={"note": "Not this term, sorry."}, headers={"X-User": COORDINATOR})
    assert r.status_code == 200 and r.json()["reply"].endswith("Not this term, sorry.")


def test_an_ask_to_another_teacher_is_in_their_inbox_and_the_answer_goes_back(demo):
    """The ask is redirected from the sender to a colleague by hand: the desk's inbox mechanics, without staging a
    real clash for make_offer."""
    c, world, desk, play = demo
    me, them = teacher(world, 6), teacher(world, 7)
    play.load([call("ask_requester", question="Would you give way in week 8?"), say("Thanks, I'll go ahead.")])
    send(c, me, "Swap with a colleague please")
    ep = desk.svc.wait(next(e.id for e in reversed(list(desk.svc.episodes.values())) if e.actor == me))
    ep.outcome.pending = ep.outcome.pending.model_copy(update={"to": them, "to_name": world.name_of(them)})
    desk.sync()
    cid = desk.case_of[ep.id]
    assert world.orch.cases[cid].status.value == "negotiating"
    items = c.get("/api/inbox", headers={"X-User": them}).json()
    item = next(i for i in items if i["case"] == cid)
    assert item["message"]["text"] == "Would you give way in week 8?" and item["reply"] is None
    assert c.post(f"/api/inbox/{item['id']}/reply", json={"decision": "accept", "choice": "A", "text": "Fine."},
                  headers={"X-User": me}).status_code == 403  # addressed to someone else
    r = c.post(f"/api/inbox/{item['id']}/reply", json={"decision": "accept", "choice": "A", "text": "Fine."},
               headers={"X-User": them})
    assert r.status_code == 200, r.text
    desk.svc.wait(ep.id)
    assert ep.status == "answered" and any(e.get("type") == "reply" and e.get("answer") == "yes" for e in ep.events)


def test_stop_and_clear(demo):
    c, world, desk, play = demo
    me = teacher(world, 0)

    def slow(messages):
        time.sleep(1.0)
        return say("done")

    play.load([slow])
    _, reply = send(c, me, "think about it slowly")
    r = c.post("/api/chat/stop", json={"episode": reply["episode"]}, headers={"X-User": me})
    assert r.status_code == 200 and desk.svc.get(reply["episode"]).status == "stopped"
    assert c.post("/api/chat/stop", json={"episode": reply["episode"]}, headers={"X-User": teacher(world, 1)}).status_code == 403
    desk.svc.wait(reply["episode"])
    thread = desk.thread_of[me]
    assert c.delete("/api/chat", headers={"X-User": me}).json()["cleared"] > 0
    play.load([say("A new conversation.")])
    _, fresh = send(c, me, "hi")
    settled(c, desk, me)
    assert desk.svc.get(fresh["episode"]).thread != thread


def test_how_it_works_describes_the_agent_loop(demo):
    c, world, desk, play = demo
    t = c.get("/api/transparency", headers={"X-User": COORDINATOR}).json()
    assert [s["name"] for s in t["lifecycle"]] == ["Read", "Look up", "Draft", "Check", "Ask", "Approve and publish"]
    assert t["agent"]["config"] and "check_draft" in t["agent"]["tools"]["evaluate"]
    assert set(t["negotiation"]) == {"max_turns", "max_tool_calls", "max_repeats", "max_seconds"}
    assert any("commit gate" in x for x in t["safety"])


def test_a_later_message_does_not_take_back_a_request_waiting_for_the_office(demo):
    c, world, desk, play = demo
    me = teacher(world, 1)
    week = (world.current_week() or 1) + 3
    day = world.instance.calendar.days[2]
    play.load([call("constrain", rule="unavailable", teacher="me", days=[FULL_DAY[day]], from_week=week, to_week=week,
                    reason="exams"),
               call("check_draft"), call("submit", message="Sent."), say("Not decided yet.")])
    send(c, me, f"away {FULL_DAY[day]} week {week}")
    cid = settled(c, desk, me)[-1]["case"]
    send(c, me, "has it been approved?")
    settled(c, desk, me)
    assert world.orch.cases[cid].status.value == "awaiting_approval"
