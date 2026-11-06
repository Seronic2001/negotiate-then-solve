"""The two fine-tuned readers of the demo app side by side, on the same queries: the request pipeline with the intents
adapter (what the Requests page runs: ``NTS_PARSER=local NTS_INTENTS=1``) and the agent loop with the agent adapter
(what the chat runs: ``web.agentic``, nts-agent-v6-dpo by default).

    uv run python -m evaluation.head_to_head                       # both systems, every query in data/head_to_head.jsonl
    uv run python -m evaluation.head_to_head --systems agent --only swap-agreed-no-possessive,move-exact
    uv run python -m evaluation.head_to_head --out runs/head_to_head/<name>   # carry on a run (done queries are skipped)

Both run on the same demo department (the web app's saved demo state, copied: the app's own state is not touched),
put back to that state before every query, in the same week, from the same sender. Other teachers answer through the
demo's simulated people (autopilot) for both, and the pipeline does not stop to let the sender pick a time (the agent
picks one itself), so each run ends on its own: a change for the office to approve, a question to the sender, an
answer, a message passed on, or a refusal. A query with a ``reply`` is answered once if the system asks the sender
something, and judged on what follows.

Colleagues asked to agree (a swap, a waived rule) say yes, for both (``Agreeable``).

A query's gold (``data/head_to_head.jsonl``):

    expect        the actions that are right (change, clarify, answer, forward, refuse)
    expect_first  for a query with a reply: what the first answer should be (a question back)
    checks        on the proposed timetables, for a change: ``at`` [session, day, hour], ``on_day`` [session, day],
                  ``between`` [session, day, from hour, to hour], ``faculty_free`` [faculty, day, hours ([]: all day)],
                  ``cancelled`` session, ``not_cancelled`` session, ``room_not`` [session, room], ``new_session``;
                  each in its ``week`` (the week's own proposal, else the semester one, else the timetable in force)
    contains      for an answer: groups of words, one of each group in the reply; ``absent``: none of these

Scored per query: the action is right, every check holds (``pass`` = both), and the time it took. The pipeline's model
answers are cached under the run's folder only, so the times are the model's. Written to the run's folder:
``results.jsonl`` (one line per query and system, everything recorded) and ``report.md`` (the summary, then each
query side by side).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parents[2]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]

ACTION = {"awaiting_approval": "change", "published": "change", "clarification_requested": "clarify",
          "answered": "answer", "forwarded": "forward", "escalated": "forward", "refused": "refuse",
          "denied": "refuse", "withdrawn": "withdrawn", "negotiating": "waiting"}


# -- the world ------------------------------------------------------------------------------------------------------

def make_world(out: Path):
    """The demo department as the web app saved it, from a copy of its demo state (``runs/state/demo/demo.pkl``)."""
    state = out / "state" / "demo"
    state.mkdir(parents=True, exist_ok=True)
    src = ROOT / "runs" / "state" / "demo" / "demo.pkl"
    if not src.exists():
        sys.exit("no saved demo state: start the web app once (uv run nts-web) so it writes runs/state/demo")
    for name in ("demo.pkl", "live.pkl"):
        shutil.copyfile(src, state / name)
    os.environ.setdefault("NTS_SEMESTER_DIR", str(out / "semester"))
    os.environ.setdefault("NTS_STUDY_DIR", str(out / "study"))
    from web.world import World, use_state_dir

    use_state_dir(out / "state")
    w = World()
    unattended(w)
    return w


def unattended(w) -> None:
    """Nobody at the screen: other teachers answer through their simulated people at once, and the pipeline takes the
    solver's first fit instead of asking the sender to pick a time (the agent picks one itself). Set again after each
    ``restore``, which brings back the demo's own autopilot settings."""
    w.orch.offer_choices = lambda: False
    w.autopilot = {f.id: True for f in w.instance.faculty}
    w.autopilot_delay = 0.0
    w.simulators = {f.id: Agreeable() for f in w.instance.faculty}


class Agreeable:
    """A colleague who says yes to the first option: the demo's simulated people each have a temper (some hold out,
    some refuse), which would decide a swap or a waived rule whichever reader read the request. Both systems get
    this one, so what differs is the reading and what is done with it."""

    def respond(self, message):
        from agents.negotiation import Reply

        return Reply(decision="accept", choice=message.offers[0].key if message.offers else "A",
                     text="Yes, that's fine.")


def baseline(w) -> dict:
    """The timetable in force in each week (None: the semester one), before the query."""
    out = {None: w.store.current_version()}
    for wk in range(1, w.instance.calendar.weeks + 1):
        out[wk] = w.store.current_version(wk) or out[None]
    return out


# -- running one query ------------------------------------------------------------------------------------------------

def run_pipeline(w, q: dict, timeout: float) -> dict:
    from core.schemas import RequestStatus

    t0 = time.time()
    r = _portal_request(w, q["sender"], q["text"])
    w.submit(r, wait=True)
    _join(w, timeout)
    case = w.orch.cases.get(r.id)
    first = _pipeline_view(w, r.id)
    replied = None
    if q.get("reply") and case is not None and case.status == RequestStatus.CLARIFICATION:
        replied = q["reply"]
        w.clarify(r.id, q["sender"], q["reply"], wait=True)
        _join(w, timeout)
    view = _pipeline_view(w, r.id)
    view.update(seconds=round(time.time() - t0, 1), first_action=first["action"], first_reply=first["reply"],
                replied=replied)
    return view


def _portal_request(w, person: str, text: str):
    """The request as the request builder makes it (``Intake.from_portal``), without its duplicate check: the saved
    demo state may hold the same words from the same sender already, and the query is meant to run again."""
    from datetime import UTC

    from core.schemas import Channel, Request
    from pipeline.ingest import normalise

    ident = next(i for i in w.directory.by_email.values() if i.person == person)
    return w.store.add_new_request(lambda rid: Request(
        id=rid, channel=Channel.PORTAL, sender_id=person, role=ident.role, raw_text=normalise(text), thread_id=rid,
        received_at=datetime.now(UTC), makeup=False))


def _join(w, timeout: float) -> None:
    end = time.time() + timeout
    for t in list(w.threads.values()):
        t.join(max(0.0, end - time.time()))


def _pipeline_view(w, rid: str) -> dict:
    case = w.orch.cases.get(rid)
    if case is None:
        events = w.store.events(rid)
        return {"action": "error", "status": "none", "reply": "", "error": events[-1] if events else "no case",
                "cases": []}
    cases = [case] + [w.orch.cases[p] for p in case.parts if p in w.orch.cases]
    actions = [ACTION.get(c.status.value, c.status.value) for c in cases[1:]] or [ACTION.get(case.status.value,
                                                                                            case.status.value)]
    action = "change" if "change" in actions else actions[0]
    errors = [e for c in cases for e in w.store.events(c.id) if e["kind"] == "error"]
    if errors and case.status.value in ("received", "classified", "policy_checked", "compiled", "solved"):
        action = "error"
    parse = case.parse
    return {
        "action": action, "status": case.status.value, "part_actions": actions if len(cases) > 1 else [],
        "reply": "\n".join(c.reply for c in cases if c.reply),
        "route": case.route, "request_type": getattr(getattr(parse, "request_type", None), "value", None),
        "understood": [u for c in cases for u in c.understood],
        "constraints": [_constraint(c2) for c in cases for c2 in c.constraints],
        "proposals": [p for c in cases for p in _proposals(c)],
        "timings": {k: round(v, 2) for c in cases for k, v in c.timings.items()},
        "negotiation_messages": sum(1 for i in w.inbox.items.values() if i.case_id in {c.id for c in cases}),
        "error": errors[-1].get("error") if errors else None,
        "cases": [c.id for c in cases],
    }


def run_agent(w, desk, q: dict, timeout: float) -> dict:
    from agents.negotiation import Reply as DemoReply
    from nts.tools import Reply
    from nts.tools.talk import REQUESTER

    t0 = time.time()
    desk.new_conversation(q["sender"])
    desk._resync(force=True)
    ep, _ = desk.send(q["sender"], q["text"])
    first, replied, asks = None, None, 0
    for _ in range(12):  # each round: the agent works, then someone answers it
        desk.svc.wait(ep.id, timeout)
        desk.sync()
        p = ep.pending
        if p is None:
            break
        if p.to == REQUESTER:
            if first is None:
                first = _agent_view(w, desk, ep)
            if not q.get("reply") or replied is not None:
                break
            replied = q["reply"]
            desk.svc.reply(ep.id, Reply(answer="said", text=q["reply"]))
            continue
        asks += 1
        items = [iid for iid, e in desk.offers.items() if e == ep.id and w.inbox.items[iid].reply is None]
        if not items:
            break
        for iid in items:  # the same agreeable colleague as the pipeline's (``Agreeable``)
            desk.answer(iid, DemoReply(decision="accept", choice="A", text="Yes, that's fine."), w.inbox.items[iid].to)
    view = _agent_view(w, desk, ep)
    first = first or view
    view.update(seconds=round(time.time() - t0, 1), first_action=first["action"], first_reply=first["reply"],
                replied=replied, teacher_asks=asks)
    return view


def _agent_view(w, desk, ep) -> dict:
    from nts.tools.talk import REQUESTER

    from web.agentic import UNFINISHED

    p = ep.pending
    cid = desk.case_of.get(ep.id)
    case = w.orch.cases.get(cid) if cid else None
    if p is not None and p.to == REQUESTER:
        action = "clarify"
    elif ep.status in UNFINISHED:
        action = "error"
    elif case is not None:
        action = ACTION.get(case.status.value, case.status.value)
    else:
        action = {"answered": "answer", "declined": "refuse", "escalated": "forward"}.get(ep.status, ep.status)
    models = [e for e in ep.events if e.get("type") == "model"]
    tools = [e for e in ep.events if e.get("type") == "tool"]
    return {
        "action": action, "status": ep.status, "case_status": case.status.value if case else None,
        "reply": (p.text if p is not None and p.to == REQUESTER else ep.text) or ep.detail,
        "detail": ep.detail, "kind": ep.kind,
        "understood": desk.svc.draft(ep.id) if ep.outcome is not None else [],
        "constraints": [_constraint(c) for c in case.constraints] if case else [],
        "proposals": _proposals(case) if case else [],
        "model_calls": len(models), "model_ms": sum(e.get("ms") or 0 for e in models),
        "tool_calls": [{"name": t["name"], "ok": t["ok"], "args": t["arguments"]} for t in tools],
        "tools_refused": sum(not t["ok"] for t in tools),
        "model_errors": sum(e.get("type") == "model_error" for e in ep.events),
        "cases": [cid] if cid else [],
    }


def _constraint(c) -> dict:
    return json.loads(c.model_dump_json(include={"type", "hard", "tier", "scope", "when", "validity"}))


def _proposals(case) -> list[dict]:
    out = []
    for v in ([case.proposal] if case.proposal else []) + list(case.more):
        out.append({"week": v.week, "assignment": {s: [p.day, p.slot, p.room] for s, p in v.assignment.items()},
                    "cancelled": list(v.cancelled)})
    return out


# -- scoring ----------------------------------------------------------------------------------------------------------

def timetable_in(view: dict, base: dict, week) -> tuple[dict, set]:
    """The assignment and cancelled sessions the system proposes for ``week``."""
    props = view.get("proposals", [])
    for want in (week, None):
        for p in props:
            if p["week"] == want:
                return p["assignment"], set(p["cancelled"])
    v = base[week]
    return {s: [p.day, p.slot, p.room] for s, p in v.assignment.items()}, set(v.cancelled)


def _day(d) -> str:
    return DAYS[d] if isinstance(d, int) else str(d)


def check(c: dict, view: dict, base: dict, inst) -> tuple[bool, str]:
    week = c.get("week")
    tt, cancelled = timetable_in(view, base, week)
    by_id = {s.id: s for s in inst.sessions}

    def where(sid):
        p = tt.get(sid)
        return None if p is None or sid in cancelled else (_day(p[0]), 9 + p[1], p[2])

    if "at" in c:
        sid, day, hr = c["at"]
        got = where(sid)
        return got is not None and got[:2] == (day, hr), f"{sid} at {got}"
    if "on_day" in c:
        sid, day = c["on_day"]
        got = where(sid)
        return got is not None and got[0] == day, f"{sid} at {got}"
    if "between" in c:
        sid, day, lo, hi = c["between"]
        got = where(sid)
        return got is not None and got[0] == day and lo <= got[1] <= hi, f"{sid} at {got}"
    if "faculty_free" in c:
        fid, day, hours = c["faculty_free"]
        busy = []
        for sid, p in tt.items():
            s = by_id.get(sid)
            if s is None or s.faculty != fid or sid in cancelled or _day(p[0]) != day:
                continue
            span = set(range(9 + p[1], 9 + p[1] + s.duration))
            if not hours or span & set(hours):
                busy.append(f"{sid}@{9 + p[1]}")
        return not busy, f"still teaching: {busy}" if busy else "free"
    if "cancelled" in c:
        return c["cancelled"] in cancelled, f"cancelled: {sorted(cancelled)}"
    if "not_cancelled" in c:
        return c["not_cancelled"] not in cancelled, f"cancelled: {sorted(cancelled)}"
    if "room_not" in c:
        sid, room = c["room_not"]
        got = where(sid)
        return got is not None and got[2] != room, f"{sid} at {got}"
    if "any" in c:
        got = [check({**x, "week": x.get("week", week)}, view, base, inst) for x in c["any"]]
        return any(ok for ok, _ in got), " | ".join(g for _, g in got)
    if "new_session" in c:  # the pipeline adds a session; the agent reserves the time ("rule: extra class: ...")
        new = [s for s in tt if s not in by_id]
        held = [u for u in view.get("understood", []) if "extra class" in u and f"week {week}" in u]
        return bool(new or held), f"new: {new}" + (f"; reserved: {held[0]}" if held else "")
    raise ValueError(f"unknown check {c}")


def score(q: dict, view: dict, base: dict, inst) -> dict:
    action_ok = view["action"] in q["expect"]
    first_ok = view["first_action"] in q["expect_first"] if q.get("expect_first") else None
    results = []
    if view["action"] == "change" or any("not_cancelled" in c for c in q.get("checks", [])):
        results = [(c, *check(c, view, base, inst)) for c in q.get("checks", [])]
    checks_ok = all(ok for _, ok, _ in results) if view["action"] == "change" else True
    text = (view.get("reply") or "").lower()
    words_ok = all(any(x.lower() in text for x in group) for group in q.get("contains", [])) and not any(
        x.lower() in text for x in q.get("absent", []))
    if not q.get("contains") and not q.get("absent"):
        words_ok = True
    return {"action_ok": action_ok, "first_ok": first_ok, "checks_ok": checks_ok, "words_ok": words_ok,
            "pass": action_ok and checks_ok and words_ok,
            "checks": [{"check": c, "ok": ok, "got": got} for c, ok, got in results]}


# -- the run ----------------------------------------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queries", default=str(ROOT / "data" / "head_to_head.jsonl"))
    ap.add_argument("--systems", default="intents,agent", help="intents, agent or both (comma-separated)")
    ap.add_argument("--only", default="", help="query ids, comma-separated")
    ap.add_argument("--out", default="", help="the run's folder (default runs/head_to_head/<time>)")
    ap.add_argument("--url", default=os.environ.get("NTS_LOCAL_URL", "http://10.1.25.191:8080/v1"))
    ap.add_argument("--timeout", type=float, default=900, help="seconds a system may take per step")
    ap.add_argument("--rescore", action="store_true", help="score the run in --out again with the current gold "
                    "(after a fix to data/head_to_head.jsonl) and rewrite its report; nothing is run")
    args = ap.parse_args()
    if args.rescore:
        return rescore(Path(args.out).resolve(), Path(args.queries))

    out = Path(args.out or ROOT / "runs" / "head_to_head" / datetime.now().strftime("%Y%m%d-%H%M")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ.update(NTS_PARSER="local", NTS_INTENTS=os.environ.get("NTS_INTENTS", "1"), NTS_LOCAL_URL=args.url,
                      NTS_AGENT_URL=os.environ.get("NTS_AGENT_URL", args.url))
    os.environ.setdefault("NTS_ADAPTERS", str(ROOT / "adapters-gpu.toml"))
    os.chdir(out)  # the pipeline's model cache (runs/llm_cache, relative) is the run's own: times are the model's

    queries = [json.loads(x) for x in Path(args.queries).read_text(encoding="utf-8").splitlines() if x.strip()]
    if args.only:
        keep = set(args.only.split(","))
        queries = [q for q in queries if q["id"] in keep]
    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    results_path = out / "results.jsonl"
    done = set()
    if results_path.exists():
        done = {(r["id"], r["system"]) for r in map(json.loads, results_path.read_text(encoding="utf-8").splitlines())}

    w = make_world(out)
    while w.snapshot is None:
        time.sleep(0.5)
    print(f"[world] {w.instance.name}, week {w.current_week()}; parser {w.models.get('parser')}", flush=True)
    desk = None
    if "agent" in systems:
        from nts.telemetry import default_tracer

        from web.agentic import AgentDesk

        desk = AgentDesk(w, tracer=default_tracer(out / "telemetry"), ticker=False)
        print(f"[agent] {desk.info()}", flush=True)

    with results_path.open("a", encoding="utf-8") as f:
        for q in queries:
            for system in systems:
                if (q["id"], system) in done:
                    continue
                w.restore()
                unattended(w)
                if desk is not None:
                    desk.svc.episodes.clear()
                    desk.case_of.clear(), desk.episode_of.clear(), desk.offers.clear(), desk.asked.clear()
                base = baseline(w)
                try:
                    view = run_pipeline(w, q, args.timeout) if system == "intents" else run_agent(w, desk, q,
                                                                                                    args.timeout)
                except Exception as e:  # noqa: BLE001 - recorded as the query's outcome
                    view = {"action": "error", "first_action": "error", "reply": "", "first_reply": "",
                            "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(), "seconds": None}
                s = score(q, view, base, w.instance)
                row = {"id": q["id"], "category": q["category"], "system": system, "text": q["text"],
                       "sender": q["sender"], **s, **view}
                f.write(json.dumps(row, default=str) + "\n")
                f.flush()
                mark = "PASS" if s["pass"] else "fail"
                print(f"[{system:7}] {q['id']:28} {mark}  {view['action']:8} {view.get('seconds')}s", flush=True)
    w.restore()
    report(results_path, out / "report.md", Path(args.queries))
    print(f"[done] {out / 'report.md'}", flush=True)
    os._exit(0)  # the world's background threads (saving, watchers) are daemons, but the agent's may still wait


def rescore(out: Path, queries_path: Path) -> None:
    os.environ["NTS_PARSER"] = "offline"  # only the department and its timetables are needed
    gold = {q["id"]: q for q in map(json.loads, queries_path.read_text(encoding="utf-8").splitlines()) if q}
    w = make_world(out / "rescore")
    while w.snapshot is None:
        time.sleep(0.5)
    w.restore()
    base = baseline(w)
    path = out / "results.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows:
        if r["id"] in gold:
            r.update(score(gold[r["id"]], r, base, w.instance))
    path.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows), encoding="utf-8")
    report(path, out / "report.md", queries_path)
    print(f"[rescored] {out / 'report.md'}", flush=True)
    sys.stdout.flush()
    os._exit(0)


# -- the report -------------------------------------------------------------------------------------------------------

def report(results_path: Path, path: Path, queries_path: Path) -> None:
    rows = [json.loads(x) for x in results_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    order = [json.loads(x)["id"] for x in queries_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    by = {(r["id"], r["system"]): r for r in rows}
    systems = [s for s in ("intents", "agent") if any(r["system"] == s for r in rows)]
    cats = sorted({r["category"] for r in rows}, key=lambda c: min(order.index(r["id"]) for r in rows
                                                                  if r["category"] == c and r["id"] in order))
    L = ["# Intents adapter (pipeline) vs agent adapter (agent loop)", "",
         f"{len({r['id'] for r in rows})} queries, same demo department and week, reset before each run.", "",
         "## Summary", "", "| system | pass | right action | checks hold | median s | mean s | errors |",
         "|---|---|---|---|---|---|---|"]
    for s in systems:
        rs = [r for r in rows if r["system"] == s]
        secs = sorted(r["seconds"] for r in rs if r.get("seconds") is not None)
        med = secs[len(secs) // 2] if secs else 0
        L.append(f"| {s} | {sum(r['pass'] for r in rs)}/{len(rs)} | {sum(r['action_ok'] for r in rs)}/{len(rs)} | "
                 f"{sum(r['checks_ok'] for r in rs if r['action'] == 'change')}/"
                 f"{sum(r['action'] == 'change' for r in rs)} changes | {med} | "
                 f"{round(sum(secs) / len(secs), 1) if secs else 0} | {sum(r['action'] == 'error' for r in rs)} |")
    L += ["", "## By category", "", "| category | n | " + " | ".join(f"{s} pass" for s in systems) + " |",
          "|---|---|" + "---|" * len(systems)]
    for c in cats:
        ids = sorted({r["id"] for r in rows if r["category"] == c})
        cells = [f"{sum(by[(i, s)]['pass'] for i in ids if (i, s) in by)}/{sum((i, s) in by for i in ids)}"
                 for s in systems]
        L.append(f"| {c} | {len(ids)} | " + " | ".join(cells) + " |")
    L += ["", "## Per query", "", "| query | category | " + " | ".join(systems) + " |", "|---|---|" + "---|" * len(systems)]
    for i in [x for x in order if any((x, s) in by for s in systems)]:
        cells = []
        for s in systems:
            r = by.get((i, s))
            cells.append("-" if r is None else f"{'✅' if r['pass'] else '❌'} {r['action']} ({r.get('seconds')}s)")
        cat = next(by[(i, s)]["category"] for s in systems if (i, s) in by)
        L.append(f"| {i} | {cat} | " + " | ".join(cells) + " |")
    L += ["", "## Side by side", ""]
    for i in [x for x in order if any((x, s) in by for s in systems)]:
        r0 = next(by[(i, s)] for s in systems if (i, s) in by)
        L += [f"### {i} ({r0['category']})", "", f"> {r0['sender']}: {r0['text']}", ""]
        for s in systems:
            r = by.get((i, s))
            if r is None:
                continue
            L.append(f"**{s}**: {'PASS' if r['pass'] else 'FAIL'}, {r['action']} (status {r.get('status')}), "
                     f"{r.get('seconds')}s")
            if r.get("replied"):
                L.append(f"- first: {r['first_action']}: {_one(r['first_reply'])}")
                L.append(f"- sender answered: {r['replied']}")
            if r.get("reply"):
                L.append(f"- says: {_one(r['reply'])}")
            if r.get("understood"):
                L.append(f"- read as: {'; '.join(r['understood'])}")
            if s == "intents" and r.get("request_type"):
                L.append(f"- request type: {r['request_type']}, route {r.get('route')}"
                         + (f", parts {r['part_actions']}" if r.get("part_actions") else ""))
            if s == "agent" and "model_calls" in r:
                L.append(f"- {r['model_calls']} model calls ({round(r['model_ms'] / 1000, 1)}s), "
                         f"{len(r['tool_calls'])} tool calls ({r['tools_refused']} refused): "
                         + ", ".join(t["name"] for t in r["tool_calls"]))
            for c in r.get("checks", []):
                L.append(f"- check {'ok' if c['ok'] else 'FAILED'}: {json.dumps(c['check'])} → {c['got']}")
            if r.get("error"):
                L.append(f"- error: {_one(str(r['error']))}")
            L.append("")
    path.write_text("\n".join(L), encoding="utf-8")


def _one(text: str, limit: int = 400) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


if __name__ == "__main__":
    main()
