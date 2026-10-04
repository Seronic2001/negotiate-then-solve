"""Several worlds in one server: the demo, and departments built from offering documents."""

import base64
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from semester.campus import campus_offerings
from semester.demo import offerings_pdf
from semester.department import instance_from_offerings
from semester.offerings import parse_offerings

pytestmark = pytest.mark.slow  # builds and solves a campus (~20 s)


def test_campus_department_from_its_pdf(tmp_path):
    pdf = tmp_path / "campus.pdf"
    pdf.write_bytes(offerings_pdf(campus_offerings()))
    doc = parse_offerings(pdf)
    assert len(doc.courses) == len(campus_offerings().courses) and not doc.warnings
    assert [c.size for c in doc.cohorts][:2] == [66, 64] and "students" not in doc.cohorts[0].name
    inst = instance_from_offerings(doc)
    roles = {f.role.value for f in inst.faculty}
    assert {"dean", "hod", "faculty", "guest_faculty"} <= roles and len(inst.groups) == 12
    shared = [s for s in inst.sessions if len(s.groups) > 1]
    assert shared and max(r.capacity for r in inst.rooms) >= max(sum(g.size for g in inst.groups if g.id in s.groups)
                                                                  for s in shared)
    assert sum("routers" in r.equipment for r in inst.rooms) == 1


def test_campus_semester_plan_solves():
    """Its labs are enough for the semester's ten lab blocks a week too, and keep their kind."""
    from semester.demo import offerings_from_instance, rooms_from_instance
    from semester.solver import SemesterSolver

    inst = instance_from_offerings(campus_offerings())
    rooms = rooms_from_instance(inst)
    assert {"computing", "electronics", "science"} <= {r.type for r in rooms}
    s = SemesterSolver(offerings_from_instance(inst), rooms=rooms, time_limit=60)
    assert not s.notes
    tt = s.solve()
    assert tt.report.status in ("optimal", "feasible") and not tt.report.hard_violations


def test_worlds_are_separate_and_built_from_documents(tmp_path, monkeypatch):
    from web.app import World, create_web_app

    monkeypatch.setenv("NTS_SEMESTER_DIR", str(tmp_path / "demo-semester"))
    app = create_web_app(World(parser_mode="offline", seed_history=False), worlds_dir=tmp_path / "worlds")
    c = TestClient(app)
    office = {"X-User": "C-TT"}
    assert [w["id"] for w in c.get("/api/worlds").json()] == ["demo"]
    data = base64.b64encode(offerings_pdf(campus_offerings())).decode()
    assert c.post("/api/worlds", json={"name": "Campus", "filename": "campus.pdf", "data": data},
                  headers={"X-User": "F-102"}).status_code == 403
    wid = c.post("/api/worlds", json={"name": "Campus", "filename": "campus.pdf", "data": data}, headers=office).json()["id"]
    for _ in range(240):
        w = next(x for x in c.get("/api/worlds").json() if x["id"] == wid)
        if w["status"] != "starting":
            break
        time.sleep(0.5)
    assert w["status"] == "ready" and w["sections"] == 12, w
    demo_people = {p["id"] for p in c.get("/api/personas").json()}
    campus_people = c.get("/api/personas", headers={"X-World": wid}).json()
    assert any(p["role"] == "guest_faculty" for p in campus_people) and any(p["role"] == "dean" for p in campus_people)
    assert {p["id"] for p in campus_people} != demo_people
    rid = c.post("/api/requests", json={"text": "I'd prefer no classes before 10 am on Monday, if possible."},
                 headers={"X-User": "F-102", "X-World": wid}).json()["id"]
    assert c.get(f"/api/cases/{rid}", headers=office | {"X-World": wid}).status_code == 200
    assert c.get(f"/api/cases/{rid}", headers=office).status_code == 404  # the demo world never saw it
    assert (Path(tmp_path) / "worlds" / "registry.json").exists()
    assert c.delete(f"/api/worlds/{wid}", headers=office).json()["deleted"] == wid
    assert c.delete("/api/worlds/demo", headers=office).status_code == 409
