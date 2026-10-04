"""Endpoints for the human study (``evaluation.study``): the team's labels for
judge validation and the anonymised faculty pilot.

A participant is known only by a code (``X-Study``), issued by the
coordinator. Labelling needs no sign-in to the portal; a pilot participant's
live session runs in the portal as the demo faculty member their code names,
and its records carry both the code and that persona.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from evaluation.study import REPLY_LABELS, TASKS, analyse

from .wording import plain

DEFAULT_PERSONA = "F-102"  # owns a practical with no special equipment: the practice clash needs one

CONSENT = [
    "Taking part is voluntary. You may stop at any time without giving a reason, and ask for your answers to be removed.",
    "You are known only by your participant code. We store no name, e-mail or other identifying detail.",
    "We store your ratings and labels, the requests and replies you type in the practice session, and when you gave them.",
    "Please do not type anything personal (health, family or other private reasons) in the practice session.",
    "The answers are used only to evaluate this project, and are reported in aggregate.",
]


class ParticipantsBody(BaseModel):
    kind: Literal["team", "pilot"]
    n: int = Field(1, ge=1, le=20)
    persona: str | None = None


CLEAR_PHRASE = "delete all study data"


class ClearBody(BaseModel):
    confirm: str  # must be CLEAR_PHRASE, typed by the coordinator


class RevokeBody(BaseModel):
    delete_answers: bool = False  # a withdrawal: erase their labels and live records too


class LabelBody(BaseModel):
    task: str
    item: str
    value: dict


class LiveBody(BaseModel):
    kind: Literal["understood", "reply", "rating"]
    case: str | None = None
    item: str | None = None  # inbox message id
    text: str | None = None
    reading: str | None = None
    confirmed: bool | None = None
    value: str | dict | None = None
    comment: str | None = Field(None, max_length=1000)


def _blind(task: str, it: dict) -> dict:
    """What a rater sees: never the configuration or the machine label."""
    if task == "claims":
        return {"id": it["id"], "claim": it["claim"], "facts": it["facts"]}
    if task == "replies":
        return {"id": it["id"], "message": plain(it["message"]), "reply": it["reply"]}
    return {"id": it["id"], "text": plain(it["text"])}  # as the portal shows it to the recipient


def _check(task: str, value: dict) -> dict:
    if task == "claims":
        if not isinstance(value.get("supported"), bool):
            raise HTTPException(422, "claims need supported: true or false")
        return {"supported": value["supported"]}
    if task == "replies":
        if value.get("label") not in REPLY_LABELS:
            raise HTTPException(422, f"label must be one of {list(REPLY_LABELS)}")
        return {"label": value["label"]}
    try:
        c, a = int(value["clarity"]), int(value["acceptability"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(422, "ratings need clarity and acceptability (1-5)") from None
    if not (1 <= c <= 5 and 1 <= a <= 5):
        raise HTTPException(422, "ratings are 1 to 5")
    out = {"clarity": c, "acceptability": a}
    if value.get("comment"):
        out["comment"] = str(value["comment"])[:1000]
    return out


def register(app: FastAPI, W: Callable, user: Callable, coordinator: Callable) -> None:
    def participant(x_study: str = Header(...)) -> dict:
        p = W().study.get(x_study)
        if p is None:
            raise HTTPException(401, "unknown participant code")
        return p

    def consented(p: dict = Depends(participant)) -> dict:
        if not p["consented"]:
            raise HTTPException(403, "consent first")
        return p

    def session(p: dict) -> dict:
        w = W()
        persona = p.get("persona")
        return p | {"persona_name": w.name_of(persona) if persona else None,
                    "tasks": w.study.tasks_for(p["kind"]),
                    "progress": w.study.progress(p["code"], p["kind"]) if w.study.items() else {},
                    "items_ready": w.study.items() is not None, "consent_text": CONSENT,
                    "reply_labels": list(REPLY_LABELS)}

    @app.get("/api/study/me")
    def me(p: dict = Depends(participant)) -> dict:
        return session(p)

    @app.post("/api/study/consent")
    def consent(p: dict = Depends(participant)) -> dict:
        return session(W().study.consent(p["code"]))

    @app.get("/api/study/next/{task}")
    def next_item(task: str, p: dict = Depends(consented)) -> dict:
        w = W()
        if task not in w.study.tasks_for(p["kind"]):
            raise HTTPException(403, "this task is not part of your session")
        done = w.study.labels().get((task, p["code"]), {})
        queue = w.study.queue(p["code"], p["kind"], task)
        todo = [i for i in queue if i["id"] not in done]
        return {"item": _blind(task, todo[0]) if todo else None, "done": len(queue) - len(todo), "total": len(queue)}

    @app.post("/api/study/labels")
    def label(body: LabelBody, p: dict = Depends(consented)) -> dict:
        w = W()
        if body.task not in TASKS or body.task not in w.study.tasks_for(p["kind"]):
            raise HTTPException(403, "this task is not part of your session")
        if body.item not in {i["id"] for i in w.study.queue(p["code"], p["kind"], body.task)}:
            raise HTTPException(404, "no such item in your session")
        w.study.label(p["code"], body.task, body.item, _check(body.task, body.value))
        return {"ok": True}

    def pilot_in_portal(p: dict = Depends(consented), u: dict = Depends(user)) -> tuple[dict, dict]:
        if p["kind"] != "pilot" or u["id"] != p["persona"]:
            raise HTTPException(403, "sign in as your study persona first")
        return p, u

    @app.post("/api/study/practice")
    def practice(pu: tuple = Depends(pilot_in_portal)) -> dict:
        p, u = pu
        w = W()
        try:
            got = w.practice_clash(u["id"])
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        w.study.live(p["code"], u["id"], "practice", **got)
        return got

    @app.post("/api/study/live")
    def live(body: LiveBody, pu: tuple = Depends(pilot_in_portal)) -> dict:
        p, u = pu
        if body.kind == "rating":
            body.value = _check("ratings", body.value if isinstance(body.value, dict) else {})
        W().study.live(p["code"], u["id"], body.kind, **body.model_dump(exclude={"kind"}, exclude_none=True))
        return {"ok": True}

    # -- coordinator ----------------------------------------------------------------------

    @app.get("/api/study/admin")
    def admin(u: dict = Depends(coordinator)) -> dict:
        w = W()
        items = w.study.items()
        ps = w.study.participants()
        return {
            "items": {t: len(items[t]) for t in TASKS} | {"pilot_ratings": sum(i["pilot"] for i in items["ratings"]),
                                                          "built": items.get("built"), "source": items.get("source")}
            if items else None,
            "participants": [{"code": c, **v, "persona_name": w.name_of(v["persona"]) if v.get("persona") else None,
                              "progress": w.study.progress(c, v["kind"]) if items else {}}
                             for c, v in sorted(ps.items())],
            "analysis": analyse(w.study) if items else None,
            "reply_parser": w.models.get("replies"),
        }

    @app.post("/api/study/participants")
    def add(body: ParticipantsBody, u: dict = Depends(coordinator)) -> dict:
        w = W()
        persona = body.persona or DEFAULT_PERSONA
        if body.kind == "pilot" and persona not in w.instance.faculty_by_id:
            raise HTTPException(422, f"{persona} is not a faculty member of this department")
        return {"codes": w.study.add_participants(body.kind, body.n, persona)}

    @app.post("/api/study/participants/{code}/revoke")
    def revoke(code: str, body: RevokeBody, u: dict = Depends(coordinator)) -> dict:
        try:
            return W().study.revoke(code, delete_answers=body.delete_answers)
        except KeyError:
            raise HTTPException(404, "no such participant") from None

    @app.post("/api/study/participants/{code}/restore")
    def restore(code: str, u: dict = Depends(coordinator)) -> dict:
        try:
            return W().study.restore(code)
        except KeyError:
            raise HTTPException(404, "no such participant") from None
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

    @app.post("/api/study/clear")
    def clear(body: ClearBody, u: dict = Depends(coordinator)) -> dict:
        if body.confirm.strip().lower() != CLEAR_PHRASE:
            raise HTTPException(422, f'type "{CLEAR_PHRASE}" to confirm')
        return {"removed": W().study.clear()}

    @app.get("/api/study/export")
    def export(u: dict = Depends(coordinator)) -> dict:
        w = W()
        return {"participants": w.study.participants(),
                "labels": [{"task": t, "code": c, "item": i, **v} for (t, c), vals in w.study.labels().items()
                           for i, v in vals.items()],
                "live": w.study.live_rows()}
