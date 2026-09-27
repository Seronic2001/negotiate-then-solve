"""JSON API behind the React front end (``frontend/``).

    uv run nts-web                        # API on http://127.0.0.1:8000 (serves frontend/dist if built)
    NTS_PARSER=gemini uv run nts-web      # System Two + policy agent on Gemini instead of the offline rules
    NTS_PARSER=local uv run nts-web       # fine-tuned compiler on llama-server (NTS_LOCAL_URL, default :8080)

One ``World`` holds a demo department and the real pipeline: intake, System
One routing, the parser (offline rules, Gemini or the local compiler), the policy agent, the
negotiator with solver-verified options, the ledger, the store and the
approval gate. Requests run in background threads; the UI follows them
through the event log. When the negotiator needs someone's answer, the
message waits in that person's inbox until they reply (or a simulator
replies for them, on request or on autopilot).

Authentication is mocked: ``POST /api/login`` accepts any directory person
and the client sends ``X-User`` with each request. Replace with the college
SSO (OIDC) for real use; authorisation decisions are already server-side.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agents.documents import SUFFIXES, ingest
from agents.explainer import TIER_NAME, describe, placement_text, session_name
from agents.ledger import ConcessionLedger
from agents.negotiation import Message, Reply
from agents.policy import BM25, Rule, tokens
from agents.priority import JUSTIFICATION, ROLE_AUTHORITY, Weights
from core.graph import add_conflict, build_graph
from core.schemas import Placement, Request, RequestStatus, Tier
from evaluation.stats import mean
from language.corpus import FULL_DAY, hour
from language.llm import FREE_TIER
from pipeline.ingest import UnknownSender
from pipeline.orchestrator import Case, NotAuthorised

from .world import (
    COORDINATOR,
    OVERSIGHT,
    ROOT,
    SEMESTER,
    VIEWS,
    InboxItem,
    World,
    views_for,
)

TIER_WHO = {0: "Nobody", 1: "Dean / academic council", 2: "Academic office", 3: "Owner, with an alternative",
            4: "Owner or HoD", 5: "Owner, freely"}
TIER_EXAMPLES = {0: "No double-booking; room capacity; lab equipment", 1: "Max 3 consecutive hours; lunch break",
                 2: "Exam blocks; guest faculty windows", 3: "Conference, medical leave, clinical duty",
                 4: "Lab needs GPUs or routers; room type", 5: "No classes before 10; fewer gaps"}


# ---------------------------------------------------------------------------
# JSON views
# ---------------------------------------------------------------------------


def _placement(w: World, p: Placement | None) -> dict | None:
    if p is None:
        return None
    return {"day": p.day, "slot": p.slot, "room": p.room, "text": placement_text(w.instance, p),
            "time": hour(p.slot)}


def _constraint(w: World, c) -> dict:
    return {"id": c.id, "type": c.type.value, "hard": c.hard, "tier": int(c.tier), "tier_name": TIER_NAME[c.tier],
            "owner": c.owner, "owner_name": w.name_of(c.owner), "text": describe(w.instance, c),
            "when": c.when.model_dump(), "justification": c.justification.value,
            "source": c.source.model_dump(), "valid": c.valid.model_dump()}


def _message(w: World, m: Message | dict) -> dict:
    m = m if isinstance(m, dict) else m.model_dump()
    return {**m, "to_name": w.name_of(m["to"]),
            "offers": [{**o, "placements": [{"session": s, "session_name": session_name(w.instance, s),
                                              **_placement(w, Placement(**p))} for s, p in o["placements"].items()]}
                       for o in m["offers"]]}


def _summary(w: World, r: Request, case: Case | None) -> dict:
    status = case.status.value if case else r.status.value
    return {"id": r.id, "sender": r.sender_id, "sender_name": w.name_of(r.sender_id), "role": r.role.value,
            "channel": r.channel.value, "text": r.raw_text, "received_at": r.received_at.isoformat(),
            "status": status, "route": case.route if case else "",
            "type": case.parse.output.request_type if case and case.parse and case.parse.output else None,
            "rounds": case.outcome.rounds if case and case.outcome else 0,
            "running": r.id in w.threads and w.threads[r.id].is_alive()}


def _case_detail(w: World, case: Case) -> dict:
    inst = w.instance
    d = _summary(w, case.request, case)
    p = case.parse
    d["routing"] = case.routing
    d["timings"] = {k: round(v, 3) for k, v in case.timings.items()}
    d["parse"] = None if p is None else {
        "action": p.action.value, "refusal": p.refusal, "errors": p.errors,
        "output": p.output.model_dump() if p.output else None,
        "constraints": [_constraint(w, c) for c in p.constraints]}
    pol = case.policy
    d["policy"] = None if pol is None else {
        "verdict": pol.verdict.value, "cited": [{"id": i, "cite": next(r.cite() for r in w.rules if r.id == i)}
                                                for i in pol.cited if any(r.id == i for r in w.rules)],
        "obligations": pol.obligations, "retrieved": pol.retrieved, "hallucinated": pol.hallucinated,
        "explanation": pol.explanation, "alternative": pol.alternative, "answer": pol.answer,
        "uncited_escalation": pol.uncited_escalation, "mode": getattr(w.policy, "mode", w.models["policy"])}
    o = case.outcome
    if o is None:
        d["outcome"] = None
    else:
        all_cons = {c.id: c for c in w.store.constraints(active_only=False)}
        d["outcome"] = {
            "status": o.status, "step": o.step, "rounds": o.rounds, "relaxed": o.relaxed,
            "mus_log": [[_constraint(w, all_cons[i]) if i in all_cons else {"id": i, "text": i} for i in mus]
                        for mus in o.mus_log],
            "messages": [_message(w, m) for m in o.messages],
            "replies": [r.model_dump(exclude_none=True) for r in o.replies],
            "concessions": [e.model_dump() | {"name": w.name_of(e.stakeholder)} for e in o.concessions],
            "notices": o.notices,
            "escalation": None if o.escalation is None else {"to": o.escalation.to, "to_name": w.name_of(
                o.escalation.to) if o.escalation.to in inst.faculty_by_id else o.escalation.to,
                "reason": o.escalation.reason, "text": o.escalation.text},
            "solver": None if o.result is None else {"status": o.result.status, "wall_time": o.result.wall_time,
                                                     "moved": o.result.moved,
                                                     "soft_violations": o.result.soft_violations}}
    if case.proposal:
        before = w.store.version(case.proposal.parent) if case.proposal.parent else None
        d["proposal"] = {"version": case.proposal.version, "week": case.proposal.week,
                         "diff": _diff(w, before.assignment if before else {}, case.proposal.assignment)}
    else:
        d["proposal"] = None
    d["fairness"] = case.fairness
    d["reply"] = case.reply
    d["notices"] = case.notices
    d["inbox"] = [_inbox_item(w, i) for i in w.inbox.items.values() if i.case_id == case.id]
    d["events"] = w.store.events(case.id)
    return d


def _diff(w: World, before: dict[str, Placement], after: dict[str, Placement]) -> list[dict]:
    out = []
    for sid in sorted(set(before) | set(after)):
        if before.get(sid) != after.get(sid):
            s = w.instance.session_by_id.get(sid)
            out.append({"session": sid, "session_name": session_name(w.instance, sid),
                        "faculty": s.faculty if s else None, "faculty_name": w.name_of(s.faculty) if s else None,
                        "groups": s.groups if s else [],
                        "before": _placement(w, before.get(sid)), "after": _placement(w, after.get(sid))})
    return out


def _inbox_item(w: World, i: InboxItem) -> dict:
    return {"id": i.id, "case": i.case_id, "to": i.to, "to_name": w.name_of(i.to),
            "created": datetime.fromtimestamp(i.created, UTC).isoformat(),
            "deadline": datetime.fromtimestamp(i.created + w.deadline, UTC).isoformat(),
            "message": _message(w, i.message),
            "reply": i.reply.model_dump(exclude_none=True) if i.reply else None,
            "answered_by": i.answered_by}


def _timetable(w: World, assignment: dict[str, Placement]) -> list[dict]:
    inst = w.instance
    rows = []
    for s in inst.sessions:
        p = assignment.get(s.id)
        if p is None:
            continue
        rows.append({"session": s.id, "course": s.course, "title": inst.course_title(s.course), "kind": s.kind.value,
                     "faculty": s.faculty, "faculty_name": w.name_of(s.faculty), "groups": s.groups,
                     "group_names": [inst.group_by_id[g].name for g in s.groups], "duration": s.duration,
                     "day": p.day, "slot": p.slot, "room": p.room,
                     "room_name": inst.room_by_id[p.room].name if p.room in inst.room_by_id else p.room})
    return rows


def _pct(xs: list[float], q: float) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(round(q / 100 * (len(xs) - 1))))]


def _llm_usage() -> list[dict]:
    cache = ROOT / "runs" / "llm_cache"
    today = date.today().isoformat()
    out = []
    counts: Counter[str] = Counter()
    if cache.exists():
        for f in cache.glob("*.json"):
            try:
                counts[json.loads(f.read_text(encoding="utf-8")).get("model", "?")] += 1
            except (OSError, ValueError):
                continue
    models = set(counts) | {m for m in FREE_TIER if (cache / f"_quota-{m}-{today}.txt").exists()}
    for m in sorted(models):
        q = cache / f"_quota-{m}-{today}.txt"
        rpm, rpd = FREE_TIER.get(m, (None, None))
        out.append({"model": m, "used_today": int(q.read_text()) if q.exists() else 0, "rpd": rpd, "rpm": rpm,
                    "cached_responses": counts.get(m, 0)})
    return out


def _experiments() -> list[dict]:
    runs = ROOT / "runs"
    out = []

    def load(name: str):
        p = runs / name
        if not p.exists():
            return None, None
        return json.loads(p.read_text(encoding="utf-8")), datetime.fromtimestamp(p.stat().st_mtime, UTC).isoformat()

    neg, at = load("negotiation-offline.json")
    probe, at2 = load("negotiation-ours-probe.json")
    if neg:
        configs = {k: v["summary"] for k, v in neg["configs"].items()}
        if probe:
            configs["ours"] = probe["configs"]["ours"]["summary"]
        out.append({"id": "negotiation", "title": "Negotiation benchmark (60 scenarios, offline)", "at": at2 or at,
                    "kind": "negotiation", "configs": configs, "paired": neg.get("paired")})
    smoke, at = load("negotiation-llm-smoke.json")
    if smoke:
        out.append({"id": "negotiation-llm", "title": "LLM configurations (3-scenario smoke run)", "at": at,
                    "kind": "negotiation", "configs": {k: v["summary"] for k, v in smoke["configs"].items()}})
    for name, title in (("parsing-lite-paraval-v2.json", "Parsing: paraphrased validation"),
                        ("parsing-lite-test-v2.json", "Parsing: templated test")):
        rep, at = load(name)
        if rep:
            two = {k: v for k, v in rep.get("system_two", {}).items() if k != "rows"}
            out.append({"id": name.removesuffix(".json"), "title": title, "at": at, "kind": "parsing",
                        "system_one": rep.get("system_one"), "system_two": two})
    pol, at = load("policy-sim-val-v1.json")
    if pol:
        out.append({"id": "policy", "title": "Policy agent: paraphrased validation", "at": at, "kind": "policy",
                    "summary": {k: v for k, v in pol.items() if k != "rows"}})
    safety = sorted(runs.glob("safety-*.json")) if runs.exists() else []
    if safety:
        rep = json.loads(safety[-1].read_text(encoding="utf-8"))
        out.append({"id": "safety", "title": f"Safety set ({safety[-1].stem.split('-')[1]} parser)",
                    "at": datetime.fromtimestamp(safety[-1].stat().st_mtime, UTC).isoformat(), "kind": "safety",
                    "summary": {k: v for k, v in rep.items() if k != "rows"}})
    return out


# ---------------------------------------------------------------------------
# The app
# ---------------------------------------------------------------------------


class LoginBody(BaseModel):
    person: str


class RequestBody(BaseModel):
    text: str


class ReplyBody(BaseModel):
    decision: str
    choice: str | None = None
    counter_days: list[str] | None = None
    counter_slots: list[int] | None = None
    text: str = ""


class RejectBody(BaseModel):
    reason: str = ""


class AutopilotBody(BaseModel):
    person: str
    on: bool


class DocumentBody(BaseModel):
    name: str
    data: str  # base64 of the file


MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


def _rule_view(r: Rule) -> dict:
    return {"id": r.id, "number": r.number, "title": r.title, "text": r.text, "source": r.source,
            "pages": list(r.pages), "method": r.method}


def create_web_app(world: World | None = None) -> FastAPI:
    state = {"w": world or World()}
    app = FastAPI(title="Negotiate, Then Solve API", version="1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def W() -> World:
        return state["w"]

    def user(x_user: str = Header(...)) -> dict:
        w = W()
        ident = next((i for i in w.directory.by_email.values() if i.person == x_user), None)
        if ident is None:
            raise HTTPException(401, "unknown user")
        return {"id": x_user, "role": ident.role.value, "name": w.name_of(x_user)}

    def coordinator(u: dict = Depends(user)) -> dict:
        if u["id"] != COORDINATOR:
            raise HTTPException(403, "only the timetable coordinator may do this")
        return u

    def view(name: str):
        def check(u: dict = Depends(user)) -> dict:
            if u["role"] not in VIEWS[name]:
                raise HTTPException(403, "not available for your role")
            return u
        return check

    def visible(u: dict, case: Case | None, r: Request) -> bool:
        if u["id"] == COORDINATOR or u["role"] in ("hod", "dean"):
            return True
        if r.sender_id == u["id"]:
            return True
        return any(i.case_id == r.id and i.to == u["id"] for i in W().inbox.items.values())

    from .semester import register as register_semester

    register_semester(app, W, user, view, coordinator)

    # -- auth (mock) ------------------------------------------------------------------

    @app.get("/api/personas")
    def personas() -> list[dict]:
        w = W()
        return [{"id": i.person, "name": w.name_of(i.person), "role": i.role.value, "email": e}
                for e, i in sorted(w.directory.by_email.items(), key=lambda x: x[1].person)]

    @app.post("/api/login")
    def login(body: LoginBody) -> dict:
        u = user(body.person)
        return u | {"views": views_for(u["role"])}

    @app.get("/api/me")
    def me(u: dict = Depends(user)) -> dict:
        return u | {"views": views_for(u["role"])}

    # -- core ---------------------------------------------------------------------------

    @app.get("/api/overview")
    def overview(u: dict = Depends(user)) -> dict:
        w = W()
        reqs = w.store.requests()
        cases = w.orch.cases
        statuses = Counter((cases[r.id].status if r.id in cases else r.status).value for r in reqs)
        teaching = sorted({s.faculty for s in w.instance.sessions})
        ledger = ConcessionLedger(w.store.ledger())
        cur = w.store.current_version()
        outcomes = [c.outcome for c in cases.values() if c.outcome]
        return {
            "department": w.instance.name, "semester": SEMESTER, "seeding": w.seeding,
            "counts": dict(statuses), "total": len(reqs),
            "pending_approvals": len(w.orch.pending()),
            "my_inbox": sum(1 for i in w.inbox.items.values() if i.to == u["id"] and i.reply is None),
            "published_version": cur.version if cur else None,
            "gini": ledger.gini(teaching, SEMESTER),
            "negotiations": {"agreed": sum(o.status == "agreed" for o in outcomes),
                             "escalated": sum(o.status == "escalated" for o in outcomes),
                             "feasible": sum(o.status == "feasible" for o in outcomes),
                             "mean_rounds": mean([o.rounds for o in outcomes if o.rounds])},
            "recent": w.store.events(limit=None)[-12:],
            "models": w.models, "sessions": len(w.instance.sessions), "faculty": len(w.instance.faculty),
            "rooms": len(w.instance.rooms), "groups": len(w.instance.groups),
        }

    @app.get("/api/instance")
    def instance(u: dict = Depends(user)) -> dict:
        w = W()
        inst = w.instance
        return {"name": inst.name, "calendar": inst.calendar.model_dump(),
                "slots": [{"slot": i, "label": hour(i)} for i in range(inst.calendar.slots_per_day)],
                "day_names": {d: FULL_DAY[d] for d in inst.calendar.days},
                "faculty": [{"id": f.id, "name": f.name, "role": f.role.value, "reports_to": f.reports_to,
                             "email": w.directory.email_of(f.id)} for f in inst.faculty],
                "groups": [g.model_dump() for g in inst.groups],
                "rooms": [r.model_dump() for r in inst.rooms],
                "sessions": [{**s.model_dump(), "title": inst.course_title(s.course)} for s in inst.sessions],
                "policy": inst.policy.model_dump()}

    @app.post("/api/requests")
    def submit(body: RequestBody, u: dict = Depends(user)) -> dict:
        w = W()
        try:
            r = w.intake.from_portal(u["id"], body.text)
        except UnknownSender:
            raise HTTPException(403, "unknown user") from None
        if r is None:
            raise HTTPException(409, "duplicate request")
        w.submit(r)
        return {"id": r.id}

    @app.get("/api/cases")
    def cases(scope: str = "mine", u: dict = Depends(user)) -> list[dict]:
        w = W()
        out = []
        for r in reversed(w.store.requests()):
            case = w.orch.cases.get(r.id)
            if scope == "mine" and r.sender_id != u["id"]:
                continue
            if visible(u, case, r):
                out.append(_summary(w, r, case))
        return out

    @app.get("/api/cases/{case_id}")
    def case(case_id: str, u: dict = Depends(user)) -> dict:
        w = W()
        r = w.store.request(case_id)
        if r is None:
            raise HTTPException(404)
        c = w.orch.cases.get(case_id)
        if not visible(u, c, r):
            raise HTTPException(403)
        if c is None:
            return {**_summary(w, r, None), "events": w.store.events(case_id)}
        return _case_detail(w, c)

    @app.get("/api/events")
    def events(after: int = 0, case: str | None = None, limit: int = 200, u: dict = Depends(user)) -> list[dict]:
        w = W()
        rows = w.store.events(case, after=after, limit=limit)
        if u["role"] in OVERSIGHT:
            return rows
        mine = {r.id for r in w.store.requests() if r.sender_id == u["id"]}
        mine |= {i.case_id for i in w.inbox.items.values() if i.to == u["id"]}
        return [e for e in rows if e.get("case") in mine]

    # -- negotiation inbox ------------------------------------------------------------------------

    @app.get("/api/inbox")
    def inbox(u: dict = Depends(user)) -> list[dict]:
        w = W()
        items = [i for i in w.inbox.items.values() if i.to == u["id"] or u["id"] == COORDINATOR]
        return [_inbox_item(w, i) for i in sorted(items, key=lambda i: -i.created)]

    @app.post("/api/inbox/{item_id}/reply")
    def reply(item_id: str, body: ReplyBody, u: dict = Depends(user)) -> dict:
        w = W()
        item = w.inbox.items.get(item_id)
        if item is None:
            raise HTTPException(404)
        if item.to != u["id"]:
            raise HTTPException(403, "this message is addressed to someone else")
        if body.decision not in ("accept", "reject", "counter"):
            raise HTTPException(422, "decision must be accept, reject or counter")
        try:
            w.inbox.answer(item_id, Reply(**body.model_dump()), u["id"])
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        return _inbox_item(w, item)

    @app.post("/api/inbox/{item_id}/simulate")
    def simulate(item_id: str, u: dict = Depends(user)) -> dict:
        w = W()
        item = w.inbox.items.get(item_id)
        if item is None:
            raise HTTPException(404)
        if u["id"] not in (item.to, COORDINATOR):
            raise HTTPException(403)
        try:
            w.inbox.answer(item_id, w.simulators[item.to].respond(item.message), "simulator")
        except ValueError as e:
            raise HTTPException(409, str(e)) from None
        return _inbox_item(w, item)

    @app.get("/api/autopilot")
    def autopilot(u: dict = Depends(user)) -> dict:
        w = W()
        return {f.id: w.autopilot.get(f.id, False) for f in w.instance.faculty}

    @app.post("/api/autopilot")
    def set_autopilot(body: AutopilotBody, u: dict = Depends(user)) -> dict:
        w = W()
        if u["id"] not in (body.person, COORDINATOR):
            raise HTTPException(403)
        w.autopilot[body.person] = body.on
        return {body.person: body.on}

    # -- approvals and versions -------------------------------------------------------------------

    @app.get("/api/approvals")
    def approvals(u: dict = Depends(view("approvals"))) -> list[dict]:
        w = W()
        return [_case_detail(w, c) for c in w.orch.pending()]

    @app.post("/api/approvals/{case_id}/approve")
    def approve(case_id: str, u: dict = Depends(user)) -> dict:
        w = W()
        try:
            v = w.orch.approve(case_id, u["id"])
        except NotAuthorised as e:
            raise HTTPException(403, str(e)) from None
        except (KeyError, ValueError) as e:
            raise HTTPException(409, str(e)) from None
        return {"version": v.version, "notified": w.orch.cases[case_id].notices}

    @app.post("/api/approvals/{case_id}/reject")
    def reject(case_id: str, body: RejectBody, u: dict = Depends(user)) -> dict:
        w = W()
        try:
            w.orch.reject(case_id, u["id"], body.reason)
        except NotAuthorised as e:
            raise HTTPException(403, str(e)) from None
        return {"status": w.orch.cases[case_id].status.value}

    @app.get("/api/versions")
    def versions(u: dict = Depends(user)) -> list[dict]:
        w = W()
        return [{**v, "approved_by_name": w.name_of(v["approved_by"]) if v["approved_by"] else None}
                for v in reversed(w.store.versions())]

    @app.get("/api/timetable")
    def timetable(version: int | None = None, week: int | None = None, u: dict = Depends(user)) -> dict:
        w = W()
        v = w.store.version(version) if version else (w.store.current_version(week) or w.store.current_version())
        if v is None:
            raise HTTPException(404)
        parent = w.store.version(v.parent) if v.parent else None
        changed = {d["session"] for d in _diff(w, parent.assignment, v.assignment)} if parent else set()
        return {"version": v.version, "week": v.week, "approved_by": v.approved_by, "parent": v.parent,
                "entries": _timetable(w, v.assignment), "changed": sorted(changed)}

    @app.get("/api/versions/diff")
    def diff(a: int, b: int, u: dict = Depends(user)) -> list[dict]:
        w = W()
        va, vb = w.store.version(a), w.store.version(b)
        if va is None or vb is None:
            raise HTTPException(404)
        return _diff(w, va.assignment, vb.assignment)

    @app.post("/api/versions/{version}/rollback")
    def rollback(version: int, u: dict = Depends(coordinator)) -> dict:
        v = W().store.rollback(version, u["id"])
        W().store.log(None, "rollback", to=version, version=v.version, approver=u["id"])
        return {"version": v.version}

    # -- transparency -------------------------------------------------------------------------------

    @app.get("/api/ledger")
    def ledger(u: dict = Depends(view("fairness"))) -> dict:
        w = W()
        entries = w.store.ledger()
        led = ConcessionLedger(entries)
        teaching = sorted({s.faculty for s in w.instance.sessions})
        return {"semester": SEMESTER, "gini": led.gini(teaching, SEMESTER), "decay": led.decay,
                "entries": [e.model_dump() | {"name": w.name_of(e.stakeholder)} for e in entries],
                "stakeholders": [{"id": f, "name": w.name_of(f), "credit": led.credit(f, SEMESTER),
                                  "concessions": led.counts().get(f, 0.0)} for f in teaching]}

    @app.get("/api/graph")
    def graph(u: dict = Depends(view("graph"))) -> dict:
        w = W()
        teaching = sorted({s.faculty for s in w.instance.sessions})
        led = ConcessionLedger(w.store.ledger())
        cons = [c for c in w.store.constraints() if c.tier >= Tier.COMMITMENT or c.owner]
        g = build_graph(w.instance, cons, {f: led.credit(f, SEMESTER) for f in teaching})
        for c in w.orch.cases.values():
            for mus in (c.outcome.mus_log if c.outcome else []):
                add_conflict(g, [i for i in mus if i in g])
        nodes = [{"id": n, **{k: v for k, v in d.items()}, "label": w.name_of(n) if d.get("kind") == "stakeholder"
                  else n} for n, d in g.nodes(data=True)]
        edges = [{"source": u_, "target": v, "rel": d.get("rel")} for u_, v, d in g.edges(data=True)]
        return {"nodes": nodes, "edges": edges}

    @app.get("/api/handbook")
    def handbook(u: dict = Depends(user)) -> list[dict]:
        return [_rule_view(r) for r in W().rules]

    @app.get("/api/handbook/documents")
    def documents(u: dict = Depends(view("documents"))) -> dict:
        w = W()
        return {"ocr": {"backend": w.ocr.name, "model": getattr(w.ocr.backend, "model", w.ocr.name)},
                "accepts": sorted(SUFFIXES), "documents": [d.summary() for d in w.documents]}

    @app.post("/api/handbook/documents")
    def upload_document(body: DocumentBody, u: dict = Depends(coordinator)) -> dict:
        import base64
        import binascii

        w = W()
        name = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(body.name).name).strip(" .")
        if not name or Path(name).suffix.lower() not in SUFFIXES or name == "handbook.md":
            raise HTTPException(422, f"unsupported file; accepted: {', '.join(sorted(SUFFIXES))}")
        try:
            data = base64.b64decode(body.data, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "data must be base64") from None
        if len(data) > MAX_DOCUMENT_BYTES:
            raise HTTPException(413, "file larger than 20 MB")
        w.policy_dir.mkdir(parents=True, exist_ok=True)
        path = w.policy_dir / name
        path.write_bytes(data)
        report = ingest(path, w.ocr)
        if report.error or not report.rules:
            path.unlink(missing_ok=True)
            raise HTTPException(422, report.error or "no text found in the document")
        w.reload_policies()
        w.store.log(None, "policy_document", name=name, rules=[r.id for r in report.rules], by=u["id"])
        return report.summary() | {"rules": [_rule_view(r) for r in w.rules if r.source == name]}

    @app.delete("/api/handbook/documents/{name}")
    def delete_document(name: str, u: dict = Depends(coordinator)) -> dict:
        w = W()
        path = w.policy_dir / Path(name).name
        if not path.is_file() or path.name == "handbook.md":
            raise HTTPException(404)
        path.unlink()
        w.reload_policies()
        return {"removed": name}

    @app.get("/api/handbook/search")
    def search(q: str, k: int = 5, u: dict = Depends(user)) -> dict:
        w = W()
        bm = BM25(w.rules)
        scores = bm.scores(q)
        ranked = sorted(zip(scores, w.rules), key=lambda x: -x[0])[:k]
        return {"query": q, "tokens": tokens(q),
                "results": [_rule_view(r) | {"score": round(s, 3)} for s, r in ranked if s > 0]}

    @app.get("/api/transparency")
    def transparency(u: dict = Depends(user)) -> dict:
        w = W()
        return {
            "tiers": [{"tier": t.value, "name": TIER_NAME[t], "who": TIER_WHO[t.value],
                       "examples": TIER_EXAMPLES[t.value], "relaxable_in_negotiation": t.value in (3, 4)}
                      for t in Tier],
            "weights": Weights().__dict__, "role_authority": {r.value: v for r, v in ROLE_AUTHORITY.items()},
            "justification": {j.value: v for j, v in JUSTIFICATION.items()},
            "ladder": [
                {"step": 1, "name": "Auto-substitute", "text": "If the hard constraints fit, repair the timetable "
                 "moving as little as possible and notify those affected."},
                {"step": 2, "name": "Auto-relax", "text": "Preferences that cannot be kept are dropped by the "
                 "objective; their owners are told and may appeal."},
                {"step": 3, "name": "Negotiate", "text": "Find the minimal conflict, the cheapest minimal corrections "
                 "(Tier 3-4 only), and ask the owner of the cheapest with 2-3 solver-verified alternatives."},
                {"step": 4, "name": "Escalate", "text": "On deadlock, no reply, or a Tier 0-2 conflict, brief the "
                 "person with authority along the reporting chain."}],
            "negotiation": {"max_rounds": 6, "options_per_message": 3, "asks_per_owner": 2,
                            "reply_deadline_s": w.deadline, "ledger_decay_per_semester": 0.5},
            "system_one": w.system_one_info, "models": w.models,
            "safety": ["Nothing is published without the coordinator's approval.",
                       "Authority is checked by code before any constraint is created; the model cannot override it.",
                       "Message text is data: models return structured data and code decides what happens.",
                       "Explanations name constraints, never private reasons; leaks are measured.",
                       "Tier 0-2 constraints are never relaxed without a named person with authority."],
        }

    @app.get("/api/observability")
    def observability(u: dict = Depends(view("health"))) -> dict:
        w = W()
        cases = list(w.orch.cases.values())
        timing = {k: [c.timings[k] for c in cases if k in c.timings] for k in ("parse", "policy", "solve_and_negotiate")}
        events = w.store.events()
        solver = [e.get("solver_seconds") for e in events if e["kind"] == "solved" and e.get("solver_seconds")]
        msgs = [m for c in cases if c.outcome for m in c.outcome.messages]
        routes = Counter(c.route for c in cases)
        s1 = [c.routing for c in cases if c.routing]
        return {
            "uptime_s": (datetime.now(UTC) - w.started).total_seconds(),
            "models": w.models, "llm": _llm_usage(),
            "stages": {k: {"n": len(v), "p50": _pct(v, 50), "p95": _pct(v, 95), "max": max(v) if v else None}
                       for k, v in timing.items()},
            "solver": {"n": len(solver), "p50": _pct(solver, 50), "p95": _pct(solver, 95)},
            "routing": {"counts": dict(routes), "tau": w.tau,
                        "system_one_latency_ms_p50": _pct([r["latency_ms"] for r in s1], 50),
                        "fast_path_share": mean([r["fast_path"] for r in s1])},
            "explanations": {"messages": len(msgs), "faithfulness": mean([m.faithfulness for m in msgs]),
                             "leaks": sum(len(m.leaks) for m in msgs),
                             "rejected_claims": sum(m.rejected_claims for m in msgs)},
            "events_by_kind": dict(Counter(e["kind"] for e in events)),
            "errors": [e for e in events if e["kind"] == "error"][-10:],
            "safety": {"refused": sum(c.status == RequestStatus.REFUSED for c in cases),
                       "denied": sum(c.status == RequestStatus.DENIED for c in cases),
                       "unapproved_publishes": 0 if all(e.get("approver") == COORDINATOR for e in events
                                                        if e["kind"] == "published") else 1,
                       "leaks": sum(len(m.leaks) for m in msgs)},
            "threads_running": sum(t.is_alive() for t in w.threads.values()),
        }

    @app.get("/api/experiments")
    def experiments(u: dict = Depends(view("experiments"))) -> list[dict]:
        return _experiments()

    @app.post("/api/demo/reset")
    def reset(u: dict = Depends(coordinator)) -> dict:
        state["w"] = World(parser_mode=W().parser_mode)
        return {"ok": True}

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles

        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str) -> FileResponse:
            f = dist / path
            if path and f.is_file():
                return FileResponse(f)
            # the page names this build's hashed chunks, so it must never be served stale:
            # an old copy asks for chunks a rebuild has deleted (404s on lazy pages)
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def run() -> None:
    import uvicorn

    uvicorn.run(create_web_app(), host=os.environ.get("NTS_HOST", "127.0.0.1"),
                port=int(os.environ.get("NTS_PORT", "8000")))
