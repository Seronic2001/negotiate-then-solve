"""The agentic demo: the chat is the agent loop (``nts``), end to end; the rest of the app is the demo app's.

Every chat message is an agent episode (``nts.api.service.Service``): the model reads the department through
its tools, drafts a change, has the kernel check it, asks the sender when something is unclear, asks the owner
of a rule that blocks the draft to waive it, and submits; the timetable office approves. The episodes of one
person's chat are one conversation, so a follow-up ("and Friday?", "make it Thursday instead") is read with the
messages before it.

The agent works on its own store (``nts.state.Store``), a mirror of the demo world: the same department, the
rules in force, the published semester timetable, each week's own timetable and the concession ledger. An
episode that does more than answer (it drafts a change, passes the request to the office, or waits for another
teacher) becomes a demo case (``pipeline.orchestrator.Case``), whose status follows the agent:

    the agent asks the sender            -> clarification_requested (answered in the chat)
    it asks a teacher to waive a rule    -> negotiating (an item in that teacher's inbox: accept, decline, counter)
    it submits a checked draft           -> awaiting_approval (the draft's timetables proposed as demo versions)
    it passes the request on             -> forwarded (the office answers it)
    the office approves                  -> published: committed through the kernel, then the same timetables
                                            published in the demo store, the rules and concessions recorded
    the office rejects, the agent declines or cannot finish  -> denied
    the sender withdraws, a later message replaces the draft -> withdrawn

so the Requests, Inbox, Approvals, Timetable, Fairness and history pages show it as they show any request.
Changes made elsewhere in the app (a request made with clicks, the semester plan, a rollback, the demo reset)
reach the agent's mirror before its next message (``_resync``): a draft made before them is stale and the
office is told to run it again.

    NTS_AGENT_MODEL    llama (default) | gemini
    NTS_AGENT_URL      llama-server's /v1 (default NTS_LOCAL_URL, else the GPU server)
    NTS_AGENT_ADAPTER  the LoRA to use, by file name (default nts-agent-v6-dpo, the best v6 in runs/eval; "" for the base model)
    NTS_AGENT          the agent configuration (default coordinator-v6, the one nts-agent-v6 was trained on)
    NTS_AGENT_PICK     0 to offer every tool to every message (default: questions get the reading tools only)
"""

from __future__ import annotations

import json
import os
import threading
import time
import weakref
from dataclasses import replace
from datetime import UTC, datetime

from agents.negotiation import EscalationBrief, Message, Offer
from agents.negotiation import Outcome as Brief
from agents.negotiation import Reply as DemoReply
from core.schemas import Channel, ConcessionEntry, Constraint, Placement, Request, RequestStatus, Role
from nts.api.service import Conflict, Episode, NotFound, Service
from nts.kernel.instance import Instance as NInstance
from nts.kernel.schemas import ConcessionEntry as NConcession
from nts.kernel.schemas import Constraint as NConstraint
from nts.notices import notices as nts_notices
from nts.state import ClassCancelled, ConstraintAdded, ConstraintRemoved, Store, TimetableSet
from nts.state.events import Conceded
from nts.tools import Reply
from nts.tools.draft import OFFICE, REP
from nts.tools.names import FULL_DAY, hour
from nts.tools.talk import REQUESTER
from pipeline.orchestrator import Case

from .world import COORDINATOR, ROOT, World

S = RequestStatus
EXTRA = "X-"  # extra classes (pipeline.store.EXTRA_PREFIX) are the demo's own: the agent's mirror leaves them out
DEFAULT_URL = "http://10.1.25.191:8080/v1"
TICK = 1.0  # seconds between the background syncs (statuses, autopilot)

# the case status an episode's status means (the ones not here: DENIED, with the agent's words)
STATUS = {"submitted": S.AWAITING_APPROVAL, "escalated": S.FORWARDED, "approved": S.PUBLISHED,
          "answered": S.ANSWERED, "replaced": S.WITHDRAWN, "stopped": S.WITHDRAWN, "withdrawn": S.WITHDRAWN,
          "undone": S.WITHDRAWN}
UNFINISHED = {"model_error": "the model could not be reached", "budget_exhausted": "it ran out of steps",
              "stuck": "it went round in circles", "interrupted": "the server restarted"}


# -- who is who: the demo's person ids and the agent's actors --------------------------------------------------

def actor_of(w: World, person: str) -> str:
    """The agent's actor for a demo person: a teacher as themselves, a class representative ("ST-G-02") as the
    section's representative, and everyone else (the timetable office, the Dean, the lab, the exam cell) as the
    office."""
    if person in w.instance.faculty_by_id:
        return person
    if person.startswith("ST-") and person[3:] in w.instance.group_by_id:
        return REP + person[3:]
    return OFFICE


def person_of(actor: str) -> str:
    if actor == OFFICE:
        return COORDINATOR
    if actor.startswith(REP):
        return "ST-" + actor[len(REP):]
    return actor


# -- the model --------------------------------------------------------------------------------------------------

def make_model():
    """The agent's model, from the environment (the module's docstring)."""
    from nts.models import GeminiChat, OpenAIChat

    if os.environ.get("NTS_AGENT_MODEL", "llama") == "gemini":
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")  # GEMINI_API_KEY
        return GeminiChat(os.environ.get("NTS_AGENT_GEMINI") or None)
    url = os.environ.get("NTS_AGENT_URL") or os.environ.get("NTS_LOCAL_URL") or DEFAULT_URL
    return OpenAIChat(url, adapter=os.environ.get("NTS_AGENT_ADAPTER", "nts-agent-v6-dpo") or None)


def make_agent():
    from nts.__main__ import AGENTS

    agent = AGENTS[os.environ.get("NTS_AGENT", "coordinator-v6")]
    if os.environ.get("NTS_AGENT_MODEL", "llama") != "gemini":  # local calls cost nothing: no token budget
        agent = replace(agent, budgets=replace(agent.budgets, max_tokens=None))
    return agent


def _picker():
    if os.environ.get("NTS_AGENT_PICK", "1") == "0":
        return None
    from nts.harness.pick import ToolPicker

    return ToolPicker.trained()


class WorldHandbook:
    """The demo world's regulations for the agent's ``rules`` tool: the handbook and every policy document
    (``data/policies``: the exam regulations, the guest-faculty circular, the lab notice, the room bookings), as
    the pipeline reads them (``World.rules``). Rebuilt when the documents change (``World.reload_policies``)."""

    def __init__(self, w: World) -> None:
        self.w, self._for, self._hb = w, None, None

    def current(self):
        from nts.policy import Handbook
        from nts.policy import Rule as NRule

        if self._for is not self.w.rules:
            self._hb = Handbook([NRule(r.id, r.number, r.title, r.text) for r in self.w.rules])
            self._for = self.w.rules
        return self._hb

    def __getattr__(self, name: str):
        return getattr(self.current(), name)


# -- the desk: one per demo world --------------------------------------------------------------------------------

_desks: weakref.WeakKeyDictionary[World, AgentDesk] = weakref.WeakKeyDictionary()
_desks_lock = threading.Lock()


def desk_of(w: World) -> AgentDesk:
    with _desks_lock:
        if w not in _desks:
            _desks[w] = AgentDesk(w)
        return _desks[w]


def agent_case(w: World, case_id: str) -> bool:
    """Whether the agent's desk carries this case (without starting a desk for a world that has none)."""
    with _desks_lock:
        d = _desks.get(w)
    return d is not None and d.owns_case(case_id)


class AgentDesk:
    def __init__(self, w: World, model=None, *, agent=None, tracer=None, picker=None, ticker: bool = True) -> None:
        from nts.telemetry import default_tracer

        self.w = w
        self.lock = threading.RLock()
        self.svc = Service(self._mirror(), model or make_model(),
                           tracer if tracer is not None else default_tracer(ROOT / "runs" / "telemetry"),
                           agent=agent or make_agent(), handbook=WorldHandbook(w),
                           picker=None if picker is False else picker if picker is not None else _picker())
        self.synced = self._mark()
        self.case_of: dict[str, str] = {}  # episode -> its demo case
        self.episode_of: dict[str, str] = {}  # demo case -> its episode
        self.thread_of: dict[str, str] = {}  # demo person -> their chat's conversation
        self.offers: dict[str, str] = {}  # demo inbox item -> the episode whose ask it is
        self.asked: dict[tuple[str, int], str] = {}  # (episode, events when it asked) -> its inbox item
        self.proposed: set[str] = set()  # episodes whose draft is proposed as demo versions
        self.declined: set[str] = set()  # cases the examination cell declined: their episode ended there
        if ticker:
            threading.Thread(target=self._tick, name="agent-desk", daemon=True).start()

    # -- the mirror -----------------------------------------------------------------

    def _mark(self) -> tuple:
        """What the agent's mirror depends on: the published versions, the rules in force and the ledger."""
        st = self.w.store
        (version,) = st._exec("SELECT COALESCE(MAX(version), 0) FROM versions WHERE published=1").fetchone()
        return version, tuple(sorted(c.id for c in st.constraints())), len(st.ledger())

    def _mirror(self) -> Store:
        w = self.w
        changes: list = [ConstraintAdded(constraint=NConstraint.model_validate(c.model_dump()))
                         for c in w.store.constraints()]

        def tt(v, week):
            return TimetableSet(week=week, assignment={s: p.model_dump() for s, p in v.assignment.items()
                                                       if not s.startswith(EXTRA)},
                                cancelled=[s for s in v.cancelled if not s.startswith(EXTRA)])

        if (sem := w.store.current_version()) is not None:
            changes.append(tt(sem, None))
        for week in range(1, w.instance.calendar.weeks + 1):
            if (v := w.store.current_version(week)) is not None:
                changes.append(tt(v, week))
        changes += [Conceded(entry=NConcession.model_validate(e.model_dump())) for e in w.store.ledger()]
        return Store.create(NInstance.model_validate(w.instance.model_dump()), changes)

    def _resync(self, force: bool = False) -> None:
        """A new mirror when the demo changed it from elsewhere, unless the agent is working on the current one
        (``force``: all the same, at approval: drafts made on the old one are rebased, ``_rebase``)."""
        if self._mark() == self.synced or (not force and any(e.busy for e in self.svc.episodes.values())):
            return
        store = self._mirror()
        from nts.bookings import Desk

        self.svc.store, self.svc.desk = store, Desk(store)
        self.synced = self._mark()

    # -- the chat ---------------------------------------------------------------------

    def send(self, person: str, text: str) -> tuple[Episode, int]:
        """A chat message: a new episode of the person's conversation, or the answer to the agent's question.
        Returns the episode and the number of its events before this message (where its reply starts)."""
        with self.lock:
            self._resync()
            thread = self.thread_of.get(person)
            if thread is not None:
                try:
                    last = self.svc.thread(thread)[-1]
                except NotFound:
                    last = None
                if last is not None and last.pending is not None and last.pending.to == REQUESTER and not last.busy:
                    start = len(last.events)
                    return self.svc.reply(last.id, Reply(answer="said", text=text)), start
            try:
                # one chat holds many requests: a later message never takes back one waiting for the office
                ep = self.svc.start(text, actor_of(self.w, person), self.w.current_week(), thread=thread,
                                    keep_drafts=True)
            except NotFound:
                ep = self.svc.start(text, actor_of(self.w, person), self.w.current_week())
            self.thread_of[person] = ep.thread
            return ep, 0

    def clarify(self, case_id: str, person: str, text: str) -> None:
        """The sender answers the agent's question from the request's page: the episode goes on, and the chat shows
        the answer and what follows, as if it had been written there."""
        text = text.strip()
        if not text:
            raise ValueError("write an answer first")
        with self.lock:
            ep = self.episode(case_id)
            if person_of(ep.actor) != person:
                raise PermissionError("only the sender answers the assistant's question")
            p = ep.pending
            if p is None or p.to != REQUESTER or ep.busy:
                raise ValueError("the assistant is not waiting for your answer")
            start = len(ep.events)
            self.svc.reply(ep.id, Reply(answer="said", text=text))
            self.w.store.add_chat(person, "you", "text", {"text": text})
            self.w.store.add_chat(person, "assistant", "agent", {"episode": ep.id, "from": start})

    def new_conversation(self, person: str) -> None:
        """The chat was cleared: the next message starts a conversation of its own."""
        self.thread_of.pop(person, None)

    def stop(self, eid: str, person: str) -> Episode:
        ep = self.svc.get(eid)
        if person_of(ep.actor) != person:
            raise PermissionError("only the person who asked can stop it")
        ep = self.svc.stop(eid)
        self.sync()
        return ep

    def message_view(self, m: dict, later: int | None) -> dict:
        """A chat message of kind "agent", as the chat draws it: the episode's events from where this message
        starts (to where the next message about the same episode starts), and, for the latest one, the answer,
        the question waiting for the sender and the request it became."""
        ep = self.svc.episodes.get(m.get("episode", ""))
        if ep is None:
            return {**m, "status": "gone", "busy": False, "steps": [], "text": m.get("text", ""), "latest": True}
        start = m.get("from", 0)
        steps = [_step(e) for e in ep.events[start:later]]
        latest = later is None
        p = ep.pending if latest else None
        cid = self.case_of.get(ep.id)
        case = self.w.orch.cases.get(cid) if cid else None
        return {**m, "status": ep.status if latest else "answered_later", "busy": ep.busy and latest,
                "steps": [s for s in steps if s], "latest": latest, "text": ep.text if latest else "",
                "detail": ep.detail if latest else "",
                "pending": None if p is None else {"kind": p.kind, "to_requester": p.to == REQUESTER, "to_name": p.to_name,
                                                   "text": p.text, "rule": p.rule_text, "weeks": p.weeks},
                "options": ep.options if p is not None and p.to == REQUESTER else [],
                "draft": self.svc.draft(ep.id) if latest and ep.outcome is not None else [],
                "case": cid, "case_status": case.status.value if case else None,
                "decision": ep.decision if latest else None}

    def chat_view(self, msgs: list[dict]) -> list[dict]:
        """The chat, its agent messages drawn from their episodes."""
        out = []
        for i, m in enumerate(msgs):
            if m.get("kind") != "agent":
                out.append(m)
                continue
            later = next((x.get("from", 0) for x in msgs[i + 1:]
                          if x.get("kind") == "agent" and x.get("episode") == m.get("episode")), None)
            out.append(self.message_view(m, later))
        return out

    # -- episodes as demo cases ---------------------------------------------------------

    def _tick(self) -> None:
        while True:
            time.sleep(TICK)
            try:
                self.sync()
                self._autopilot()
            except Exception:  # noqa: BLE001 -- the next tick tries again; the requests themselves show errors
                pass

    def sync(self) -> None:
        """Bring every case in line with its episode (idempotent; run every ``TICK`` and after each action)."""
        with self.lock:
            for ep in list(self.svc.episodes.values()):
                self._reconcile(ep)

    def _reconcile(self, ep: Episode) -> None:
        if ep.busy:
            return  # it is settled when the agent stops: running, a case keeps the status it had
        p = ep.pending
        cid = self.case_of.get(ep.id)
        if cid is None:
            becomes = (ep.status in ("submitted", "escalated", "approved", "rejected")
                       or (p is not None and p.to != REQUESTER)
                       or (ep.status == "declined" and bool(self.svc.draft(ep.id))))  # a change it found cannot be done
            if not becomes:
                return  # an answer, or a question to the sender: it stays in the chat
            cid = self._open_case(ep)
        case = self.w.orch.cases.get(cid)
        if case is None:  # the demo was reset: the case is gone
            return
        if self.episode_of.get(cid) != ep.id or cid in self.declined:
            return  # the examination cell decided it: a later episode carries the case on, or it ended declined
        if p is not None:
            status = S.CLARIFICATION if p.to == REQUESTER else S.NEGOTIATING
            if p.to != REQUESTER:
                self._offer(ep, case)
        else:
            status = STATUS.get(ep.status, S.DENIED)
        exams = self._exams(ep) if ep.status == "escalated" else None
        if exams is not None:
            status = S.ESCALATED
        if ep.status == "submitted" and ep.id not in self.proposed:
            self._propose(ep, case)
        if status == S.PUBLISHED:
            return  # set by approve, with the version
        reply = self._reply(ep)
        if case.status != status or (reply and case.reply != reply):
            if reply:
                case.reply = reply
            if case.status != status:
                if exams is not None:
                    self._to_exam_cell(case, exams)
                self._advance(case, status, agent_status=ep.status, **({"reason": ep.detail} if ep.detail else {}),
                              **({"to": "exam_cell", "cited": exams.cited} if exams is not None else {}))
                if exams is not None:
                    self.w._on_escalated(case)
            if status in (S.WITHDRAWN, S.DENIED):
                self._close_offers(ep.id)

    @staticmethod
    def _exams(ep: Episode):
        """The examination regulations' ruling, when the agent passed the request on because a change next to the
        examinations needs the Controller of Examinations' approval (``nts.tools.evaluate``); None otherwise."""
        run = ep.outcome.run if ep.outcome is not None else None
        return run.ctx.scratch.get("exams") if run is not None else None

    def _to_exam_cell(self, case: Case, ruling) -> None:
        """The request goes to the examination cell (role exam_cell) to decide, as in the pipeline: granted, the
        agent makes the change and it goes to the office's approval (``decide``)."""
        asked = case.request.raw_text.strip()
        weeks = ", ".join(map(str, ruling.weeks))
        brief = (f"{self.w.name_of(case.request.sender_id)} asks for a change in week{'s' if len(ruling.weeks) > 1 else ''}"
                 f" {weeks}, next to the examinations: \"{asked}\". Under {', '.join(ruling.cited)} no change may take "
                 "effect in the weeks around the examinations without the Controller of Examinations' written "
                 "approval: grant it if no examination is affected.")
        case.outcome = Brief(status="escalated", step=0, escalation=EscalationBrief(
            to="exam_cell", reason=ruling.reason, text=brief, rule=ruling.cited[0] if ruling.cited else None,
            asked=asked, grant="The assistant makes the change and it goes to the timetable office for approval."))

    def decide(self, case_id: str, decider: str, grant: bool, note: str = "", name: str = "") -> None:
        """The examination cell's decision on a request sent to it. Granted: the agent works on the request again
        with the examination check lifted, and the change goes to the office's approval like any other.
        Declined: the sender is told, and the agent remembers it."""
        case = self.w.orch.cases[case_id]
        if case.status != S.ESCALATED:
            raise ValueError(f"case {case_id} is not escalated ({case.status.value})")
        name = name or self.w.name_of(decider)
        with self.lock:
            old = self.episode(case_id)
            case.decision = {"by": decider, "granted": grant, "note": note, "set_aside": []}
            if not grant:
                self.declined.add(case_id)
                case.reply = f"Your request was declined by {name}" + (f": {note}" if note else ".")
                self.svc.note(old.id, case.reply)
                self._advance(case, S.DENIED, decided_by=decider, note=note)
                return
            self.svc.note(old.id, f"Approved by {name}" + (f": {note}" if note else "."))
            ep = self.svc.start(old.request, old.actor, old.week, exams_granted=True)
            self.episode_of[case_id], self.case_of[ep.id] = ep.id, case_id
            self._advance(case, S.COMPILED, decided_by=decider, granted=True, note=note, set_aside=[], episode=ep.id)

    def _reply(self, ep: Episode) -> str:
        if ep.status in UNFINISHED:
            return (f"The assistant could not finish this request: {UNFINISHED[ep.status]}. Nothing was changed; "
                    "send it again.")
        if ep.status == "rejected":
            note = (ep.decision or {}).get("note", "")
            return "The timetable office did not approve this" + (f": {note.rstrip('.')}." if note else ".")
        if ep.status == "submitted":
            return ep.text or "Sent to the timetable office for approval."
        return ep.text or ep.detail

    def _open_case(self, ep: Episode) -> str:
        w = self.w
        person = person_of(ep.actor)
        ident = next((i for i in w.directory.by_email.values() if i.person == person), None)
        role = ident.role if ident else Role.COORDINATOR
        # no dedupe key: the same words sent again are a request of their own (the agent decided they were one)
        r = w.store.add_new_request(lambda rid: Request(id=rid, channel=Channel.PORTAL, sender_id=person, role=role,
                                                        raw_text=ep.request, thread_id=rid,
                                                        received_at=datetime.now(UTC)))
        case = Case(request=r, route="agent", routing={"reader": "agent", "episode": ep.id, "kind": ep.kind})
        w.orch.cases[r.id] = case
        w.store.log(r.id, "received", channel="chat", sender=person, episode=ep.id)
        self.case_of[ep.id], self.episode_of[r.id] = r.id, ep.id
        return r.id

    def _advance(self, case: Case, status: RequestStatus, **info) -> None:
        case.request.status = status  # the agent's lifecycle, not the pipeline's: no transition table
        self.w.store.save_request(case.request)
        self.w.store.log(case.id, status.value, **info)

    def _propose(self, ep: Episode, case: Case) -> None:
        """The draft's timetables as demo versions waiting for approval, so the office sees the change as a diff."""
        assert ep.outcome is not None
        d = ep.outcome.draft
        weeks = [wk for wk, tt in d.world.timetables.items() if d.base.timetables.get(wk) is not tt]
        versions = []
        for wk in sorted(weeks, key=lambda x: -1 if x is None else x):
            tt = d.world.timetables[wk]
            versions.append(self.w.store.propose_version(
                {s: Placement.model_validate(p.model_dump()) for s, p in tt.assignment.items()}, case.id,
                week=wk, cancelled=sorted(tt.cancelled)))
        case.proposal, case.more = (versions[0], versions[1:]) if versions else (None, [])
        case.understood = self.svc.draft(ep.id)
        base = d.base.constraints
        case.constraints = [Constraint.model_validate(c.model_dump()) for cid, c in d.world.constraints.items()
                            if cid not in base]
        self.proposed.add(ep.id)

    # -- talking to other teachers: the inbox ----------------------------------------------

    def _offer(self, ep: Episode, case: Case) -> None:
        """The agent's ask to another teacher, as an item in their inbox (once per ask)."""
        p = ep.pending
        key = (ep.id, len(ep.events))
        if p is None or key in self.asked:
            return
        weeks = (f"in week {', '.join(map(str, p.weeks))}" if len(p.weeks) == 1 else
                 f"in weeks {', '.join(map(str, p.weeks))}" if p.weeks else "from now on")
        consent = getattr(p, "consent", False)  # a swap with this teacher's class: nothing of theirs is waived
        text = (p.text if p.kind != "offer" else
                f"{p.text}\n\nAccept agrees to the swap, Decline keeps your class where it is." if consent else
                f"{p.text}\n\nYour rule: {p.rule_text}. Waive it {weeks}? Accept says yes, Decline says no, or suggest "
                "another time for the class instead.")
        drop = [p.rule] if p.rule and not consent else []
        swap = getattr(p, "swap", None) if consent else None
        if swap:  # the swap card: who asks in one line, then the two classes before and after
            me = self.w.name_of(case.request.sender_id)
            text = (f"{me} would like to swap classes with you {weeks}.\n\n{p.text}\n\n"
                    "Accept agrees to the swap, Decline keeps your class where it is.")
        placements = {sid: Placement(**at) for sid, at in swap.items()} if swap else {}
        offers = [Offer(key="A", drop=drop, placements=placements)] if p.kind == "offer" else []
        msg = Message(round=sum(1 for k in self.asked if k[0] == ep.id) + 1, to=p.to, mus=drop,
                      offers=offers, text=text, explanation_mode="swap" if swap else "agent", faithfulness=1.0)
        item = self.w.inbox.add(case.id, p.to, msg)
        self.asked[key], self.offers[item.id] = item.id, ep.id
        self.w.store.log(case.id, "negotiation_message", to=p.to, round=msg.round, agent=True)

    def owns_item(self, item_id: str) -> bool:
        return item_id in self.offers

    def answer(self, item_id: str, demo: DemoReply, by: str) -> None:
        """A teacher's answer to the agent's ask, from the inbox: accept (yes), decline (no), a counter-offer (a
        day and hour for the requester's class), or their own words."""
        eid = self.offers[item_id]
        if demo.decision == "accept":
            r = Reply(answer="yes", text=demo.text or "Yes, that's fine.")
        elif demo.decision == "reject":
            r = Reply(answer="no", text=demo.text or "No, sorry.")
        elif demo.decision in ("counter", "propose") and (demo.counter_days or demo.proposal):
            day = demo.proposal.day if demo.proposal else demo.counter_days[0]
            slot = demo.proposal.slot if demo.proposal else (demo.counter_slots or [0])[0]
            r = Reply(answer="counter", day=FULL_DAY.get(day, day), hour=hour(slot), text=demo.text)
        elif demo.decision == "no_reply":
            r = Reply(answer="no_reply")
        else:
            r = Reply(answer="said", text=demo.text)
        with self.lock:
            self.w.inbox.answer(item_id, demo, by)
            self.svc.reply(eid, r)
            if (cid := self.case_of.get(eid)) is not None:
                self.w.store.log(cid, "negotiation_reply", by=by, decision=demo.decision or "said", agent=True)
        self.sync()

    def simulate(self, item_id: str) -> None:
        """The demo's "simulate a reply": the teacher's stand-in answers (those whose demo profile turns down the
        first message, or refuses more often than not, say no)."""
        item = self.w.inbox.items[item_id]
        prof = self.w.profiles.get(item.to)
        yes = prof is None or (not prof.holds_out and prof.refuse_p < 0.5)
        self.answer(item_id, DemoReply(decision="accept" if yes else "reject", choice="A" if yes else None,
                                       text="Yes, that's fine." if yes else "No, sorry, I can't."), item.to)

    def _autopilot(self) -> None:
        now = time.time()
        for iid, _ in list(self.offers.items()):
            item = self.w.inbox.items.get(iid)
            if (item is not None and item.reply is None and self.w.autopilot.get(item.to)
                    and now - item.created >= self.w.autopilot_delay):
                try:
                    self.simulate(iid)
                except (Conflict, ValueError, KeyError):
                    pass

    def _close_offers(self, eid: str) -> None:
        for iid, e in self.offers.items():
            item = self.w.inbox.items.get(iid)
            if e == eid and item is not None and item.reply is None:
                try:
                    self.w.inbox.answer(iid, DemoReply(decision="no_reply"), "withdrawn")
                except ValueError:
                    pass

    # -- the office --------------------------------------------------------------------------

    def owns_case(self, case_id: str) -> bool:
        return case_id in self.episode_of

    def episode(self, case_id: str) -> Episode:
        return self.svc.get(self.episode_of[case_id])

    def approve(self, case_id: str, approver: str) -> int | None:
        """Commit the case's draft through the kernel, then publish the same timetables in the demo store and
        record its rules and concessions there. Returns the demo version (None: nothing in the timetable moved)."""
        with self.lock:
            self._resync(force=True)
            eid = self.episode_of[case_id]
            case = self.w.orch.cases[case_id]
            self._rebase(self.svc.get(eid))
            before = len(self.svc.store.events)
            ep = self.svc.approve(eid)
            if ep.status != "approved":
                self._reconcile(ep)
                raise Conflict("the kernel did not accept the draft: the timetable changed since; run it again")
            assert ep.outcome is not None
            committed = [e.change for e in self.svc.store.events[before:]]
            st = self.w.store
            for ch in committed:
                if isinstance(ch, ConstraintAdded):
                    c = Constraint.model_validate(ch.constraint.model_dump())  # its request, as the demo names it
                    st.add_constraints([c.model_copy(update={"source": c.source.model_copy(update={"request": case_id})})],
                                       request_id=case_id)
                elif isinstance(ch, ConstraintRemoved):
                    st.set_active(ch.id, False)
                elif isinstance(ch, Conceded):
                    st.record_concession(ConcessionEntry.model_validate(ch.entry.model_dump()))
            published = [st.publish_version(v.version, approver) for v in ([case.proposal] if case.proposal else [])
                         + case.more]
            told = nts_notices(ep.outcome.draft.base, self.svc.store.world, ep.actor)
            case.notices = {person_of(a): " ".join(lines) for a, lines in told.items()}
            case.reply = ("The timetable office approved it: " + "; ".join(self.svc.draft(eid)) + "."
                          if self.svc.draft(eid) else "The timetable office approved it.")
            version = published[0].version if published else None
            self._advance(case, S.PUBLISHED, version=version, approver=approver, notified=sorted(case.notices),
                          agent_status="approved", **({"more": [v.version for v in published[1:]]} if len(published) > 1 else {}))
            self.synced = self._mark()
            return version

    def _rebase(self, ep: Episode) -> None:
        """A draft made before other changes were published (someone else's request approved first, a change made
        with clicks): its changes again on the timetable as it is now, when none of the timetables it writes has
        changed since; the commit gate then checks the result against everything in force. When one has, it is
        not guessed at: the office is told to run the request again."""
        out = ep.outcome
        if out is None or ep.status != "submitted" or out.draft.base.version == self.svc.store.version:
            return
        old, now = out.draft.base, self.svc.store.world
        weeks = {ch.week for ch in out.draft.changes if isinstance(ch, TimetableSet | ClassCancelled)}
        moved = [w for w in weeks if _same(old.timetable(w)) != _same(now.timetable(w))]
        if moved:
            when = ", ".join("the semester timetable" if w is None else f"week {w}" for w in sorted(moved, key=lambda w: w or 0))
            raise Conflict(f"{when} changed since this draft was made; ask for it again in the chat")
        draft = self.svc.store.draft(out.draft.actor, out.draft.episode)
        try:
            for ch in out.draft.changes:
                draft.add(ch)
        except ValueError as e:
            raise Conflict(f"the draft no longer applies: {e}; ask for it again in the chat") from None
        out.draft = draft

    def reject(self, case_id: str, approver: str, reason: str) -> None:
        with self.lock:
            self.svc.reject(self.episode_of[case_id], note=reason)
            self._reconcile(self.episode(case_id))

    def handle(self, case_id: str, by: str, note: str, name: str) -> Case:
        """The office answers a request the agent passed to it: the answer is the sender's reply (and the agent
        remembers it in the conversation)."""
        note = note.strip()
        if not note:
            raise ValueError("write a reply first")
        case = self.w.orch.cases[case_id]
        if case.handled is not None:
            raise ValueError(f"case {case_id} has already been answered")
        with self.lock:
            self.svc.note(self.episode_of[case_id], note)
            case.handled = {"by": by, "note": note, "at": datetime.now().isoformat(timespec="seconds")}
            case.reply = f"Reply from {name}: {note}"
            self.w.store.log(case_id, "handled", by=by, note=note)
        return case

    def withdraw(self, case_id: str, person: str) -> Case:
        """The sender takes it back: the agent stops, its asks are closed and its draft never reaches the timetable."""
        case = self.w.orch.cases[case_id]
        if case.request.sender_id != person:
            raise PermissionError("only the sender can withdraw it")
        if case.status in (S.PUBLISHED, S.WITHDRAWN, S.DENIED, S.ANSWERED):
            raise ValueError(f"it can no longer be withdrawn ({case.status.value})")
        with self.lock:
            ep = self.episode(case_id)
            if ep.busy:
                self.svc.stop(ep.id)
            else:
                ep.status, ep.detail = "withdrawn", "withdrawn by the sender"
                ep.push({"type": "end", "status": "withdrawn", "text": "", "detail": ep.detail})
            self._reconcile(ep)
        return case

    def info(self) -> dict:
        """What the How it works page says about the agent: its model, configuration, budgets and tools by scope."""
        from dataclasses import asdict

        from nts.tools import ALL_TOOLS

        m, agent = self.svc.harness.model, self.svc.agent
        model = getattr(m, "model", None) or getattr(m, "name", None) or type(m).__name__
        tools: dict[str, list[str]] = {}
        for t in ALL_TOOLS:
            if t.scope in agent.scopes:
                tools.setdefault(t.scope.value, []).append(t.name)
        eps = list(self.svc.episodes.values())
        return {"model": str(model), "adapter": getattr(m, "adapter", None), "url": getattr(m, "base_url", None),
                "config": agent.name, "budgets": asdict(agent.budgets), "tools": tools,
                "picker": self.svc.harness.picker is not None,
                "episodes": len(eps), "requests": len(self.case_of),
                "approved": sum(e.status == "approved" for e in eps)}

    def trace(self, case_id: str) -> dict | None:
        """The agent's side of a case, for its page: every step, the draft, and how it ended."""
        eid = self.episode_of.get(case_id)
        ep = self.svc.episodes.get(eid) if eid else None
        if ep is None:
            return None
        return {"episode": ep.id, "status": ep.status, "busy": ep.busy, "text": ep.text, "detail": ep.detail,
                "request": ep.request, "kind": ep.kind, "draft": self.svc.draft(ep.id), "decision": ep.decision,
                "steps": [s for s in (_step(e) for e in ep.events) if s]}


# -- events as the chat shows them ---------------------------------------------------------------------------------

def _same(tt) -> tuple | None:
    """A timetable as what it says (where each class is, which are not held), to compare two versions of it."""
    return None if tt is None else (tuple(sorted(tt.assignment.items())), tuple(sorted(tt.cancelled)))


def _short(value, limit: int = 700) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _step(e: dict) -> dict | None:
    """One event of an episode, small enough to send every few seconds: what the model said and which tools it
    called, each tool's result (cut short), each ask and its answer, how it ended, the office's decision."""
    t = e.get("type")
    if t == "model":
        return {"type": "model", "text": e.get("text", ""), "calls": [c["name"] for c in e.get("calls", [])],
                "ms": e.get("ms")}
    if t == "tool":
        return {"type": "tool", "name": e.get("name"), "ok": e.get("ok"), "arguments": _short(e.get("arguments", {}), 300),
                "result": _short(e.get("result")), "ms": e.get("ms")}
    if t == "reply":
        return {"type": "reply", "kind": e.get("kind"), "to": e.get("to"), "text": e.get("text"),
                "rule": e.get("rule"), "answer": e.get("answer"), "says": e.get("says", "")}
    if t in ("waiting", "end"):
        return {"type": t, "status": e.get("status"), "text": e.get("text", ""), "detail": e.get("detail", "")}
    if t == "decision":
        return {"type": "decision", "approved": e.get("approved"), "note": e.get("note", ""), "by": e.get("by")}
    if t == "note":
        return {"type": "note", "text": e.get("text", "")}
    if t == "model_error":
        return {"type": "model_error", "error": _short(e.get("error"), 300)}
    return None
