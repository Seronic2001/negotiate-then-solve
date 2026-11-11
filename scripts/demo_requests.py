"""Thirty requests that show the agent app working end to end, through the HTTP API, as the people who send them.

    PYTHONPATH=src .venv/Scripts/python.exe scripts/demo_requests.py                      # a fresh demo department
    PYTHONPATH=src .venv/Scripts/python.exe -m nts serve --store runs/agentic/demo-30.jsonl \\
        --telemetry runs/telemetry-demo30 --model llama --agent coordinator-v6 --adapter nts-agent-v6-dpo --port 8101
    # then open http://127.0.0.1:8101/ and sign in as anyone: every request below is there, with what came of it

The department is ``nts init``'s (seed 1: 8 teachers, 3 sections). The requests name its real classes in week 5
(the current week) and later weeks, and are sent in this order, as a story: class representatives ask about their
sections' weeks, report a clash that is not one, and ask for changes, which the agent passes to the office; teachers
ask, cancel, move, swap and set rules, and colleagues whose classes move are asked first (the script answers for
them); the office closes a room, acts on a class rep's request and decides on every draft (one is turned down); a
club books a room; and the reps then see what changed in their sections' timetables.

Each step's result is checked against what it should come to (``expect``: the episode's final status), and a report
is written to runs/eval/demo-30.json and runs/eval/demo-30.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from nts.agents import COORDINATOR_V6
from nts.api import Service, create_app
from nts.harness.pick import ToolPicker
from nts.kernel.generator import generate_department
from nts.kernel.instance import policy_constraints
from nts.models import OpenAIChat
from nts.policy import Handbook
from nts.state import Store, bootstrap
from nts.telemetry import default_tracer

S1, S2, S3 = "rep: Section 1", "rep: Section 2", "rep: Section 3"
OFFICE = "office"
ANSWERED, SUBMITTED, ESCALATED = "answered", "submitted", "escalated"


@dataclass
class Step:
    who: str  # a teacher's name, OFFICE, a class rep ("rep: Section 1") or a club ("club: Robotics")
    text: str
    expect: str | tuple[str, ...] = ANSWERED  # the status the agent should end with (before the office decides)
    week: int = 5
    follow: int | None = None  # continues the conversation of that step (1-based)
    say: list[str] = field(default_factory=list)  # the requester's answers to the agent's questions, in order
    colleague: str = "yes"  # how a teacher the agent asks about their class answers
    office: str = "approve"  # what the office does with a draft: approve / reject; with an escalation: its reply
    note: str = ""  # the office's note (a rejection's reason, or its reply to a request passed on)
    booking: dict | None = None  # a club's room booking (no agent)


STEPS: list[Step] = [
    # -- a normal Monday: class reps and teachers ask about the week --------------------------------------------
    Step(S1, "What classes do we have on Monday?"),
    Step("Dr. Iyer", "When am I free on Wednesday?"),
    Step(S2, "When are we free on Wednesday afternoon? We want to plan a study group."),
    Step(OFFICE, "Which rooms are free on Thursday at 2 pm?"),
    Step(S3, "Where is our Computer Graphics practical this week, and who takes it?"),
    Step("Dr. Rao", "What do I teach on Tuesday?"),
    Step(S1, "Our Operating Systems lecture and Computer Networks lecture both seem to be on Tuesday at 2 pm. "
             "Is that a clash?"),
    Step(S2, "Is there a rule about how many hours of classes in a row we can have?"),
    Step("Dr. Menon", "How much notice do I need to give to move one of my classes?"),
    # -- changes: an absence, a move, and a class rep's request the office acts on ------------------------------
    Step("Dr. Das", "I'm at a conference on Thursday of week 6. Please move my classes that day.", SUBMITTED,
         say=["Move them to another day that week, please."]),
    Step("Dr. Pillai", "Please move my Operating Systems lecture on Friday at 12 pm in week 6 to Thursday at 9 am.",
         SUBMITTED),
    Step(S1, "Most of our class takes the 5 pm bus home. Could our Friday 4 pm Machine Learning lecture be moved "
             "earlier in the day, from next week on?", ESCALATED,
         note="We asked Dr. Rao and are moving it to Friday morning from week 6. You will see it in your timetable."),
    Step(OFFICE, "Move Dr. Rao's Machine Learning lecture on Friday at 4 pm to a Friday morning hour (9 am to 12 pm), "
                 "from week 6 to the end of term. Section 1 asked for it.", SUBMITTED,
         say=["Any free hour on Friday morning is fine."]),
    Step(S1, "Thanks! Has our Machine Learning lecture been moved now? Where is it in week 6?", follow=12),
    Step("Dr. Menon", "Could I swap my Tuesday 10 am Algorithms lecture with my Computer Architecture lecture on "
                      "Thursday at 4 pm, in week 6 only?", SUBMITTED, say=["Yes, swap those two, in week 6 only."]),
    Step(S2, "Where is our Algorithms lecture in week 6? I heard it moved.", week=5),
    Step("Dr. Sharma", "Please keep my Monday mornings free from week 7 onwards.", SUBMITTED),
    Step("Dr. Gupta", "Please cancel my Data Structures lecture on Monday at 2 pm in week 8, I'm on jury duty.",
         SUBMITTED),
    Step("Dr. Gupta", "And please add a make-up Data Structures lecture later that week, Thursday afternoon if possible.",
         SUBMITTED, follow=18, say=["Thursday afternoon, any free hour."]),
    Step(OFFICE, "Lab 2 is closed for maintenance on Tuesday of week 7.", SUBMITTED),
    Step(S3, "Did anything change in our timetable in week 7?", week=7),
    Step("Dr. Khan", "I'd like no classes after 4 pm on Fridays from now on.", (SUBMITTED, ANSWERED)),
    Step("Dr. Iyer", "Can my Database Systems practical on Thursday at 2 pm in week 6 move to Friday afternoon?",
         SUBMITTED),
    Step(S3, "We'd like an extra Information Security class in week 7 to prepare for the mid-term. Is that possible?",
         ESCALATED, note="Dr. Das has agreed to an extra class. The office will add it this week."),
    Step("Dr. Sharma", "I'm away at a workshop on Tuesday and Wednesday of week 9. Please move my classes on those days.",
         SUBMITTED, say=["Any other day that week is fine."]),
    Step("Dr. Pillai", "Please move my Distributed Systems lecture on Wednesday at 4 pm to Monday at 9 am from week 6 on.",
         (SUBMITTED, "declined"), office="reject",
         note="Section 3 already starts Monday with a 9 am class most weeks; keep Wednesday for now."),
    Step(OFFICE, "Who is free on Monday at 10 am?"),
    Step("club: Robotics", "Book Room 103 for the Robotics club workshop, Wednesday of week 6, 4 to 5 pm, 40 people.",
         booking={"purpose": "Robotics workshop", "week": 6, "day": "Wednesday", "from_hour": "4 pm",
                  "to_hour": "5 pm", "attendees": 40, "room": "Room 103"}),
    Step("Dr. Rao", "If possible, I'd rather not teach before 10 am on Mondays.", SUBMITTED),
    Step(S2, "A lot of us commute from far away. Could our Friday 9 am Software Engineering practical move later in "
             "the day?", ESCALATED,
         note="Thank you. Dr. Gupta's Friday is full this term; we will look at it for next semester."),
]


def episode_view(client: TestClient, eid: str) -> dict:
    return client.get(f"/api/episodes/{eid}").json()


def run(args: argparse.Namespace) -> int:
    if args.fresh or not args.store.exists():
        if args.store.exists():
            args.store.unlink()
        inst = generate_department(seed=1, n_faculty=8, n_groups=3, n_lecture_rooms=4, n_labs=3)
        bootstrap(inst, policy_constraints(inst), path=args.store)
    store = Store.open(args.store)
    model = OpenAIChat(args.url, adapter=args.adapter, temperature=0.0, timeout=240.0)
    # the GPU server's context is 8,192 tokens and the prompt estimate runs ~20% short on long episodes: leave room
    agent = replace(COORDINATOR_V6, budgets=replace(COORDINATOR_V6.budgets, max_tokens=None, max_seconds=600.0,
                                                    context_tokens=args.context_tokens))
    hb = Handbook.load(Path("data/handbook.md")) if Path("data/handbook.md").exists() else None
    svc = Service(store, model, default_tracer(args.telemetry), agent=agent, handbook=hb, picker=ToolPicker.trained())
    app = create_app({"demo": svc})
    clients: dict[str, TestClient] = {}

    def as_(who: str) -> TestClient:
        if who not in clients:
            c = TestClient(app)
            r = c.post("/api/login", json={"dept": "demo", "name": who, "password": ""})
            r.raise_for_status()
            clients[who] = c
        return clients[who]

    threads: dict[int, str] = {}
    rows: list[dict] = []
    steps = STEPS[args.start - 1: args.stop]
    for n, st in enumerate(steps, start=args.start):
        t0 = time.time()
        me = as_(st.who)
        row = {"n": n, "who": st.who, "request": st.text, "week": st.week, "expect": st.expect}
        print(f"[{n:2}] {st.who}: {st.text}", flush=True)
        if st.booking:
            r = me.post("/api/bookings", json=st.booking)
            got = r.json()
            row.update(status=got.get("status", f"http {r.status_code}"), answer=json.dumps(got, ensure_ascii=False),
                       ok=r.status_code == 200 and got.get("status") in ("booked", "needs_approval"))
            if got.get("status") == "needs_approval":
                as_(OFFICE).post(f"/api/bookings/{got['id']}/approve")
                row["office"] = "approved the booking"
            rows.append(row)
            print(f"     -> {row['status']}", flush=True)
            continue
        body = {"request": st.text, "week": st.week, "simulate": False}
        if st.follow and st.follow in threads:  # (a run started past that step: a new conversation)
            body["thread"] = threads[st.follow]
        r = me.post("/api/episodes", json=body)
        if r.status_code != 200:
            row.update(status=f"http {r.status_code}", answer=r.text, ok=False)
            rows.append(row)
            print(f"     !! {r.text}", flush=True)
            continue
        ep = r.json()
        threads[n] = ep["thread"]
        said, talks = list(st.say), []
        for _ in range(6):  # the agent's questions: to the requester, or to a teacher whose class moves
            svc.wait(ep["id"], timeout=900)
            d = episode_view(me, ep["id"])
            p = d.get("pending")
            if d["status"] != "waiting" or not p:
                break
            if p["to_requester"]:
                text = said.pop(0) if said else "Whatever works best, thank you."
                talks.append(f"agent asked {st.who}: {p['text']} / answered: {text}")
                me.post(f"/api/episodes/{ep['id']}/reply", json={"answer": "said", "text": text})
            else:
                who = p["to"]
                talks.append(f"agent asked {who} ({p['kind']}): {p['text']} / {who} said {st.colleague}")
                as_(who).post(f"/api/episodes/{ep['id']}/reply", json={"answer": st.colleague, "text": ""})
        d = episode_view(me, ep["id"])
        events = svc.get(ep["id"]).events
        tools = [e["name"] for e in events if e["type"] == "tool"]
        expect = st.expect if isinstance(st.expect, tuple) else (st.expect,)
        row.update(status=d["status"], answer=d["text"] or d["detail"], draft=d.get("draft", []), tools=tools,
                   talks=talks, ok=d["status"] in expect, episode=ep["id"], thread=ep["thread"])
        office = as_(OFFICE)
        if d["status"] == SUBMITTED:
            if st.office == "reject":
                office.post(f"/api/episodes/{ep['id']}/reject", json={"note": st.note})
                row["office"] = f"rejected: {st.note}"
            else:
                got = office.post(f"/api/episodes/{ep['id']}/approve", json={"note": st.note}).json()
                row["office"] = got.get("status")
        elif d["status"] == ESCALATED and st.note:
            office.post(f"/api/episodes/{ep['id']}/note", json={"note": st.note})
            row["office"] = f"replied: {st.note}"
        row["seconds"] = round(time.time() - t0, 1)
        rows.append(row)
        print(f"     -> {row['status']}{' ok' if row['ok'] else ' (expected ' + '/'.join(expect) + ')'}"
              f"{' · office ' + str(row.get('office')) if row.get('office') else ''} · {row['seconds']} s"
              f"\n     {row['answer'][:300]}", flush=True)
        for t in talks:
            print(f"     · {t}", flush=True)

    # what each class rep was told: the section's changes
    told = {s: as_(s).get("/api/notices").json() for s in (S1, S2, S3)}
    ok = sum(r["ok"] for r in rows)
    report = {"at": datetime.now().isoformat(timespec="seconds"), "store": str(args.store), "model": model.name,
              "agent": agent.name, "passed": ok, "of": len(rows), "steps": rows, "class_reps_told": told,
              "version": store.version}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    md = [f"# Demo: {len(rows)} requests ({ok} as expected)", "",
          f"{report['at']} · model `{model.name}` · agent `{agent.name}` · store `{args.store}`", "",
          "| # | Who | Request | Ended | Office | OK |", "|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['n']} | {r['who']} | {r['request']} | {r['status']} | {r.get('office', '')} | "
                  f"{'yes' if r['ok'] else 'no'} |")
    md += ["", "## What the class representatives were told", ""]
    for s, items in told.items():
        md.append(f"**{s.removeprefix('rep: ')}**")
        md += [f"- {i['kind']}: {i['text']}" for i in reversed(items)] or ["- nothing"]
        md.append("")
    args.out.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    print(f"\n{ok}/{len(rows)} as expected; report {args.out}", flush=True)
    return 0 if ok == len(rows) else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--store", type=Path, default=Path("runs/agentic/demo-30.jsonl"))
    p.add_argument("--telemetry", type=Path, default=Path("runs/telemetry-demo30"))
    p.add_argument("--url", default="http://10.1.25.191:8080/v1")
    p.add_argument("--adapter", default="nts-agent-v6-dpo")
    p.add_argument("--out", type=Path, default=Path("runs/eval/demo-30.json"))
    p.add_argument("--context-tokens", type=int, default=6000, help="one call's prompt budget (the server has 8192)")
    p.add_argument("--fresh", action="store_true", help="start from a new department (the store is replaced)")
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--stop", type=int, default=len(STEPS))
    args = p.parse_args()
    assert len(STEPS) == 30
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
