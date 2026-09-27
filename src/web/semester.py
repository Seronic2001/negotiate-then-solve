"""HTTP endpoints for the semester timetable and club activities (mounted by ``web.app``)."""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Callable
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from agents.policy import BM25
from semester.clubs import ClubRequest
from semester.offerings import elective_pools


class TextBody(BaseModel):
    text: str
    preview: bool = False


class FileBody(BaseModel):
    name: str | None = None
    data: str | None = None  # base64
    sample: bool = False


class SizesBody(BaseModel):
    sizes: dict[str, int]


class NoteBody(BaseModel):
    note: str = ""


class ClubBody(BaseModel):
    request: ClubRequest
    submit: bool = False


class DecideBody(BaseModel):
    approve: bool


def register(app: FastAPI, W: Callable, user: Callable, view: Callable, coordinator: Callable) -> None:
    def planner():
        return W().semester

    def overview_of(p, full: bool) -> dict:
        doc = p.state.doc
        pools = {x.id: x for x in doc.pools} if doc else {}
        pub = p.published()
        out = {
            "loaded": doc is not None,
            "source": doc.source if doc else None,
            "semester_start": p.state.semester_start,
            "calendar": p.calendar.model_dump(),
            "published": pub.version if pub else None,
            "cohorts": [{"id": c.id, "name": c.name, "size": p.state.sizes.get(c.id, 0), "courses": c.courses,
                         "electives": c.electives,
                         "elective_pools": [{"slot": slot, "pools": [{"id": x, "name": pools[x].name,
                                                                      "courses": pools[x].courses} for x in ids]}
                                            for slot, ids in elective_pools(doc, c)]}
                        for c in (doc.cohorts if doc else [])],
            "rooms": [r.model_dump() for r in p.rooms],
        }
        if full and doc:
            needs = p.needs()
            out |= {
                "courses": [c.model_dump() | {"needs": needs.get(c.code, [])} for c in doc.courses.values()],
                "pools": [x.model_dump() for x in doc.pools],
                "warnings": doc.warnings,
                "preferences": [x.model_dump() for x in p.state.preferences],
                "closures": [c.model_dump() for c in p.state.closures],
                "versions": [{"version": v.version, "created": v.created, "kind": v.kind, "note": v.note,
                              "published": v.published, "based_on": v.based_on, "moved": len(v.diff),
                              "report": v.timetable.report.model_dump(exclude={"room_use"})} for v in p.state.versions],
                "sample_available": bool(p.sample and p.sample.exists()),
            }
        return out

    @app.get("/api/semester")
    def semester(u: dict = Depends(view("semester"))) -> dict:
        return overview_of(planner(), full=True)

    @app.get("/api/semester/public")
    def semester_public(u: dict = Depends(user)) -> dict:
        return overview_of(planner(), full=False)

    @app.post("/api/semester/offerings")
    def offerings(body: FileBody, u: dict = Depends(coordinator)) -> dict:
        p = planner()
        if body.sample:
            if not (p.sample and p.sample.exists()):
                raise HTTPException(404, "no sample offering document")
            path = p.sample
        else:
            name = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(body.name or "offerings.pdf").name)
            try:
                data = base64.b64decode(body.data or "", validate=True)
            except (binascii.Error, ValueError):
                raise HTTPException(422, "data must be base64") from None
            path = p.folder / name
            path.write_bytes(data)
        try:
            doc = p.load_offerings(path)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        return {"courses": len(doc.courses), "cohorts": len(doc.cohorts), "pools": len(doc.pools),
                "warnings": doc.warnings}

    @app.post("/api/semester/sizes")
    def sizes(body: SizesBody, u: dict = Depends(coordinator)) -> dict:
        planner().set_sizes(body.sizes)
        return {"ok": True}

    @app.post("/api/semester/preferences")
    def add_preference(body: TextBody, u: dict = Depends(view("prefs"))) -> dict:
        try:
            return planner().add(body.text, u["name"], preview=body.preview)
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

    @app.get("/api/semester/preferences")
    def my_preferences(u: dict = Depends(view("prefs"))) -> list[dict]:
        p = planner()
        mine = [x for x in p.state.preferences if u["role"] == "coordinator" or x.source == u["name"]]
        return [x.model_dump() for x in mine]

    @app.delete("/api/semester/preferences/{pid}")
    def delete_preference(pid: str, u: dict = Depends(view("prefs"))) -> dict:
        p = planner()
        pref = next((x for x in p.state.preferences if x.id == pid), None)
        if pref is None:
            raise HTTPException(404)
        if u["role"] != "coordinator" and pref.source != u["name"]:
            raise HTTPException(403, "you can remove only your own preferences")
        p.remove_preference(pid)
        return {"removed": pid}

    @app.post("/api/semester/build")
    def build(body: NoteBody, u: dict = Depends(coordinator)) -> dict:
        try:
            planner().start("build", body.note or "semester build")
        except (ValueError, RuntimeError) as e:
            raise HTTPException(409, str(e)) from None
        return planner().status()

    @app.post("/api/semester/changes")
    def change(body: TextBody, u: dict = Depends(coordinator)) -> dict:
        p = planner()
        if p.published() is None:
            raise HTTPException(409, "publish a timetable before proposing changes to it")
        parsed = p.add(body.text, u["name"], preview=body.preview)
        if not parsed["ok"] or body.preview:
            return parsed
        try:
            p.start("change", body.text)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(409, str(e)) from None
        return parsed | {"status": p.status()}

    @app.get("/api/semester/status")
    def status(u: dict = Depends(view("semester"))) -> dict:
        return planner().status()

    @app.get("/api/semester/timetable")
    def timetable(version: int | None = None, u: dict = Depends(view("semester"))) -> dict:
        p = planner()
        v = next((x for x in p.state.versions if x.version == version), None) if version else (
            p.published() or (p.state.versions[-1] if p.state.versions else None))
        if v is None:
            raise HTTPException(404, "no timetable built yet")
        return {"version": v.version, "published": v.published, "kind": v.kind, "note": v.note, "diff": v.diff,
                "meetings": [m.model_dump() for m in v.timetable.meetings], "report": v.timetable.report.model_dump()}

    @app.post("/api/semester/versions/{version}/publish")
    def publish(version: int, u: dict = Depends(coordinator)) -> dict:
        try:
            v = planner().publish(version)
        except KeyError:
            raise HTTPException(404) from None
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        return {"published": v.version}

    # -- clubs ------------------------------------------------------------------------------

    def rules_for(req: ClubRequest) -> list[dict]:
        rules = W().rules
        hits = BM25(rules).search(f"club event activity room booking auditorium notice {req.activity}", 3)
        return [{"id": r.id, "title": r.title, "source": r.source, "text": r.text} for r in hits]

    @app.post("/api/clubs")
    def club(body: ClubBody, u: dict = Depends(view("clubs"))) -> dict:
        req = body.request.model_copy(update={"requested_by": u["id"]})
        try:
            return planner().club(req, body.submit, rules_for(req)).model_dump()
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

    @app.get("/api/clubs")
    def clubs(u: dict = Depends(view("clubs"))) -> list[dict]:
        bookings = planner().state.bookings
        mine = bookings if u["role"] == "coordinator" else [b for b in bookings if b.request.requested_by == u["id"]]
        return [b.model_dump() for b in reversed(mine)]

    @app.post("/api/clubs/{booking}/decide")
    def decide(booking: str, body: DecideBody, u: dict = Depends(coordinator)) -> dict:
        try:
            return planner().decide(booking, body.approve).model_dump()
        except StopIteration:
            raise HTTPException(404) from None
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
