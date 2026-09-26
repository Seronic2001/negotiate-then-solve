"""The front end's API over the real pipeline (offline parser and policy)."""

import time

import pytest as _pytest

pytestmark = _pytest.mark.slow  # starts real solves in background threads (~75 s)

import pytest
from fastapi.testclient import TestClient

from nts.web import COORDINATOR, World, create_web_app


@pytest.fixture(scope="module")
def client():
    world = World(parser_mode="offline", seed_history=False, deadline=60)
    return TestClient(create_web_app(world)), world


def as_(person):
    return {"X-User": person}


def wait_for(c, case_id, statuses, user=COORDINATOR, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        d = c.get(f"/api/cases/{case_id}", headers=as_(user)).json()
        if d["status"] in statuses:
            return d
        time.sleep(0.3)
    raise AssertionError(f"{case_id} stuck in {d['status']}")


def test_mock_auth(client):
    c, _ = client
    people = c.get("/api/personas").json()
    assert any(p["id"] == COORDINATOR for p in people) and any(p["role"] == "student" for p in people)
    assert c.post("/api/login", json={"person": "F-104"}).json()["name"] == "Dr. Khan"
    assert c.get("/api/me", headers=as_("nobody")).status_code == 401


def test_request_to_publication(client):
    c, world = client
    rid = c.post("/api/requests", json={"text": "I'm at a conference in week 7, Tuesday and Wednesday."},
                 headers=as_("F-104")).json()["id"]
    d = wait_for(c, rid, {"awaiting_approval"})
    assert d["routing"]["tau"] > 0 and d["policy"]["obligations"] == ["P-MAKEUP"]
    assert d["parse"]["constraints"][0]["tier"] == 3 and d["proposal"]["week"] == 7
    assert c.get(f"/api/cases/{rid}", headers=as_("F-105")).status_code == 403  # not theirs
    assert c.post(f"/api/approvals/{rid}/approve", headers=as_("F-104")).status_code == 403
    v = c.post(f"/api/approvals/{rid}/approve", headers=as_(COORDINATOR)).json()["version"]
    assert c.get("/api/timetable?week=7", headers=as_("F-104")).json()["version"] == v
    kinds = [e["kind"] for e in c.get(f"/api/events?case={rid}", headers=as_(COORDINATOR)).json()]
    assert kinds[0] == "received" and kinds[-1] == "published"


def test_interactive_negotiation_through_the_inbox(client):
    c, world = client
    inst = world.instance
    pract = {s.faculty: s for s in inst.sessions if s.kind.value == "practical" and not s.equipment}
    rao, menon = pract["F-101"], pract["F-102"]
    first = c.post("/api/requests", json={"text": f"My {inst.course_title(rao.course)} practical needs the routers, "
                                                  "and it has to be on Tuesday afternoon."}, headers=as_("F-101")).json()
    wait_for(c, first["id"], {"awaiting_approval"})
    c.post(f"/api/approvals/{first['id']}/approve", headers=as_(COORDINATOR))
    second = c.post("/api/requests", json={"text": f"My {inst.course_title(menon.course)} practical needs routers "
                                                   "too; it must be on Tuesday afternoon."}, headers=as_("F-102")).json()
    d = wait_for(c, second["id"], {"negotiating", "escalated"})
    assert d["status"] == "negotiating"
    end = time.time() + 60
    items = []
    while time.time() < end and not items:
        items = [i for i in c.get("/api/inbox", headers=as_(COORDINATOR)).json()
                 if i["case"] == second["id"] and i["reply"] is None]
        time.sleep(0.3)
    item = items[0]
    msg = item["message"]
    assert msg["offers"] and msg["facts"] and all(cl["supported"] for cl in msg["claims"])
    other = "F-102" if item["to"] == "F-101" else "F-101"
    assert c.post(f"/api/inbox/{item['id']}/reply", json={"decision": "accept", "choice": "A"},
                  headers=as_(other)).status_code == 403
    r = c.post(f"/api/inbox/{item['id']}/reply", json={"decision": "accept", "choice": "A"}, headers=as_(item["to"]))
    assert r.status_code == 200
    d = wait_for(c, second["id"], {"awaiting_approval"})
    assert d["outcome"]["status"] == "agreed" and d["outcome"]["concessions"]
    assert d["proposal"]["diff"]


def test_transparency_endpoints(client):
    c, _ = client
    h = as_("F-104")
    s = c.get("/api/handbook/search?q=1pm lunch", headers=h).json()
    assert s["results"][0]["id"] == "P-LUNCH" and "h13" in s["tokens"]
    t = c.get("/api/transparency", headers=h).json()
    assert len(t["tiers"]) == 6 and t["ladder"][2]["name"] == "Negotiate"
    g = c.get("/api/graph", headers=h).json()
    assert any(e["rel"] == "reports_to" for e in g["edges"])
    assert "gini" in c.get("/api/ledger", headers=h).json()
    o = c.get("/api/observability", headers=h).json()
    assert "stages" in o and "llm" in o
    assert isinstance(c.get("/api/experiments", headers=h).json(), list)
    assert c.get("/api/instance", headers=h).json()["slots"][4]["label"] == "1 pm"
    assert c.post("/api/demo/reset", headers=h).status_code == 403
