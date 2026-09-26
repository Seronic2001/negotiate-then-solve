"""Orchestrator: the request lifecycle (proposal Figure 2) end to end.

Received -> Classified (System One routes: fast path to the compiler, or
System Two) -> Policy checked (RAG) -> Compiled + validated -> Solved
(CP-SAT repair) -> Negotiating (resolution ladder) -> Fairness audited ->
Awaiting approval -> Published + notified.

Safe exits: Refused (no authority), Denied (policy, with citation and
alternative), Clarification requested, Escalated, Answered, Forwarded.

Safety properties enforced here, not by any model:

* nothing is published except by ``approve`` from a listed approver;
* message text never reaches a state-changing call: models return data,
  and only this code decides what happens with it;
* replies and notices are built from constraints, never from private reasons.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .corpus import ExpectedAction
from .explainer import describe, placement_text, session_name
from .graph import add_change, affected_stakeholders, build_graph, moved_sessions
from .instance import Instance
from .ledger import ConcessionLedger
from .negotiation import Negotiator, Outcome, Responder
from .parsing import ParseResult
from .policy import PolicyAgent, PolicyDecision, Verdict
from .schemas import Constraint, Request, RequestStatus, TimetableVersion
from .solver import TimetableSolver
from .store import Store

S = RequestStatus


class NotAuthorised(PermissionError):
    pass


@dataclass
class Case:
    request: Request
    route: str = ""
    parse: ParseResult | None = None
    policy: PolicyDecision | None = None
    constraints: list[Constraint] = field(default_factory=list)
    outcome: Outcome | None = None
    proposal: TimetableVersion | None = None
    fairness: dict = field(default_factory=dict)
    reply: str = ""
    notices: dict[str, str] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.request.id

    @property
    def status(self) -> RequestStatus:
        return self.request.status


class Orchestrator:
    def __init__(
        self,
        instance: Instance,
        store: Store,
        *,
        parser,
        negotiator: Negotiator,
        fast_parser=None,
        system_one=None,
        tau: float = 0.9,
        policy_agent: PolicyAgent | None = None,
        responders: Mapping[str, Responder] | None = None,
        approvers: Iterable[str] = ("C-TT",),
        semester: str = "current",
    ) -> None:
        self.instance = instance
        self.store = store
        self.parser = parser
        self.fast_parser = fast_parser
        self.system_one = system_one
        self.tau = tau
        self.policy = policy_agent
        self.negotiator = negotiator
        self.responders = dict(responders or {})
        self.approvers = set(approvers)
        self.semester = semester
        self.cases: dict[str, Case] = {}

    # -- setup -------------------------------------------------------------------

    def bootstrap(self, constraints: Iterable[Constraint], assignment=None, approved_by: str = "bootstrap") -> None:
        """Load the constraints in force and publish the starting timetable."""
        constraints = list(constraints)
        self.store.add_constraints(constraints)
        if assignment is None:
            result = TimetableSolver(self.instance, constraints, time_limit=60).solve()
            if not result.ok:
                raise RuntimeError(f"cannot build the starting timetable: {result.status}")
            assignment = result.assignment
        v = self.store.propose_version(assignment, case_id="bootstrap")
        self.store.publish_version(v.version, approved_by)
        self.store.log(None, "bootstrap", version=v.version)

    # -- the lifecycle ---------------------------------------------------------------

    def _advance(self, case: Case, status: RequestStatus, **info) -> None:
        case.request.advance(status)
        self.store.save_request(case.request)
        self.store.log(case.id, status.value, **info)

    def _parse(self, case: Case) -> ParseResult:
        r = case.request
        if self.system_one is not None and self.fast_parser is not None:
            d = self.system_one.decide(r)
            if d.fast_path(self.tau):
                case.route = "fast"
                return self.fast_parser.parse(r)
        case.route = "system_two"
        return self.parser.parse(r)

    def submit(self, request: Request) -> Case:
        case = Case(request=request)
        self.cases[case.id] = case
        if self.store.request(request.id) is None:
            self.store.add_request(request)
        self.store.log(case.id, "received", channel=request.channel.value, sender=request.sender_id)

        case.parse = self._parse(case)
        self._advance(case, S.CLASSIFIED, route=case.route, action=case.parse.action.value)
        action = case.parse.action

        if action == ExpectedAction.REFUSE:
            case.reply = f"Your request was not processed: {case.parse.refusal}. The timetable coordinator has been informed."
            self._advance(case, S.REFUSED, reason=case.parse.refusal)
            return case
        if action == ExpectedAction.ANSWER:
            if self.policy is None:
                case.reply = "Your question has been passed to the timetable coordinator."
                self._advance(case, S.FORWARDED, to="coordinator")
                return case
            case.policy = self.policy.review(request.raw_text, case.parse)
            case.reply = case.policy.answer or case.policy.explanation
            self._advance(case, S.ANSWERED, cited=case.policy.cited)
            return case
        if action in (ExpectedAction.INVESTIGATE, ExpectedAction.OUT_OF_SCOPE):
            to = "coordinator" if action == ExpectedAction.INVESTIGATE else "the relevant office"
            case.reply = f"Thank you. Your message has been passed to {to}."
            self._advance(case, S.FORWARDED, to=to)
            return case

        # compile or clarify: check policy first
        if self.policy is not None and action == ExpectedAction.COMPILE:
            case.policy = self.policy.review(request.raw_text, case.parse)
        self._advance(case, S.POLICY_CHECKED,
                      verdict=case.policy.verdict.value if case.policy else "not_checked")
        if action == ExpectedAction.CLARIFY:
            out = case.parse.output
            case.reply = (out.clarifying_question if out and out.clarifying_question else
                          "Could you give the days, times and weeks you mean?")
            self._advance(case, S.CLARIFICATION, missing=out.missing if out else [])
            return case
        if case.policy and case.policy.verdict == Verdict.FORBIDDEN:
            case.reply = (f"Your request cannot be granted: {case.policy.explanation}"
                          + (f" Alternative: {case.policy.alternative}" if case.policy.alternative else ""))
            self._advance(case, S.DENIED, cited=case.policy.cited)
            return case
        if case.policy and case.policy.verdict == Verdict.NEEDS_APPROVAL:
            case.reply = f"Your request needs approval and has been sent up: {case.policy.explanation}"
            self._advance(case, S.ESCALATED, reason="needs approval", cited=case.policy.cited)
            return case

        case.constraints = case.parse.constraints
        self.store.add_constraints(case.constraints, request_id=case.id)
        self._advance(case, S.COMPILED, constraints=[c.id for c in case.constraints],
                      obligations=case.policy.obligations if case.policy else [])
        return self._solve(case)

    def _solve(self, case: Case) -> Case:
        weeks = sorted({w for c in case.constraints for w in (c.when.weeks or [])})
        week = weeks[0] if weeks else None
        base = self.store.current_version(week) or self.store.current_version()
        baseline = base.assignment if base else None
        ledger = ConcessionLedger(self.store.ledger())
        self.negotiator.ledger = ledger
        self.negotiator.priority.ledger = ledger
        self.negotiator.priority.baseline = dict(baseline or {})
        outcome = self.negotiator.resolve(self.store.constraints(), self.responders, baseline=baseline, week=week)
        case.outcome = outcome
        self._advance(case, S.SOLVED, feasible=outcome.rounds == 0 and outcome.status == "feasible")
        if outcome.status != "feasible":
            self._advance(case, S.NEGOTIATING, rounds=outcome.rounds)
        if outcome.status == "escalated":
            case.reply = "Your request conflicts with others and has been escalated for a decision."
            self._advance(case, S.ESCALATED, to=outcome.escalation.to, reason=outcome.escalation.reason,
                          brief=outcome.escalation.text)
            return case

        for cid in outcome.relaxed:
            self.store.set_active(cid, False)
        known = {c.id for c in self.store.constraints(active_only=False)}
        self.store.add_constraints([c for c in outcome.constraints if c.id not in known], request_id=case.id)
        for e in outcome.concessions:
            self.store.record_concession(e)
        case.fairness = self._audit(outcome)
        self._advance(case, S.FAIRNESS_AUDITED, **case.fairness)

        case.proposal = self.store.propose_version(outcome.result.assignment, case.id, week=week)
        moved = moved_sessions(baseline or {}, outcome.result.assignment)
        case.reply = ("Your request can be met. The change is waiting for the coordinator's approval."
                      if not outcome.notices.get(case.request.sender_id) else
                      " ".join(outcome.notices[case.request.sender_id]))
        self._advance(case, S.AWAITING_APPROVAL, version=case.proposal.version, moved=moved)
        return case

    def _audit(self, outcome: Outcome) -> dict:
        teaching = sorted({s.faculty for s in self.instance.sessions})
        ledger = ConcessionLedger(self.store.ledger())
        before = ConcessionLedger([e for e in ledger.entries if e not in outcome.concessions])
        return {"gini_before": round(before.gini(teaching, self.semester), 4),
                "gini_after": round(ledger.gini(teaching, self.semester), 4),
                "conceded": sorted({e.stakeholder for e in outcome.concessions}),
                "preferences_lost": sorted(outcome.notices)}

    # -- human approval (L6) -------------------------------------------------------------

    def pending(self) -> list[Case]:
        return [c for c in self.cases.values() if c.status == S.AWAITING_APPROVAL]

    def approve(self, case_id: str, approver: str) -> TimetableVersion:
        if approver not in self.approvers:
            self.store.log(case_id, "approval_refused", approver=approver)
            raise NotAuthorised(f"{approver} may not approve timetable changes")
        case = self.cases[case_id]
        if case.status != S.AWAITING_APPROVAL or case.proposal is None:
            raise ValueError(f"case {case_id} is not awaiting approval ({case.status.value})")
        before = self.store.current_version(case.proposal.week) or self.store.current_version()
        v = self.store.publish_version(case.proposal.version, approver)
        moved = moved_sessions(before.assignment if before else {}, v.assignment)
        g = build_graph(self.instance)
        add_change(g, f"V{v.version}", moved)
        case.notices = self._notices(g, f"V{v.version}", moved, v)
        self._advance(case, S.PUBLISHED, version=v.version, approver=approver, notified=sorted(case.notices))
        return v

    def reject(self, case_id: str, approver: str, reason: str = "") -> None:
        if approver not in self.approvers:
            raise NotAuthorised(f"{approver} may not review timetable changes")
        case = self.cases[case_id]
        self._advance(case, S.NEGOTIATING, rejected_by=approver, reason=reason)

    def _notices(self, g, change: str, moved: list[str], v: TimetableVersion) -> dict[str, str]:
        people = affected_stakeholders(g, change)
        out = {}
        for person in sorted(people):
            mine = [s for s in moved if s in v.assignment and (
                any(x.id == s and x.faculty == person for x in self.instance.sessions) or
                any(x.id == s and f"ST-{grp}" == person for x in self.instance.sessions for grp in x.groups))]
            if mine:
                week = f" (week {v.week})" if v.week else ""
                out[person] = "Timetable change" + week + ": " + "; ".join(
                    f"{session_name(self.instance, s)} is now on {placement_text(self.instance, v.assignment[s])}"
                    for s in mine)
        return out


def explain_constraint(instance: Instance, c: Constraint) -> str:
    """What the coordinator sees for a constraint (no private reasons)."""
    return describe(instance, c)
