"""Evaluate tools: ask the kernel what the draft would do.

``check_draft`` re-solves every timetable the draft's new rules touch, as a repair of the timetable
that runs there now (moving as few classes as it can), and says in words what moves, who else it
affects, which wishes are not met, or, when it cannot be done, which rules clash. A clashing rule
another teacher set is numbered, so the agent can ask them to waive it (``make_offer``). The timetables it
found are kept (``ctx.scratch["check"]``) for ``submit``, which accepts them only for the exact draft
version they were solved for.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from nts.exams import exam_ruling
from nts.kernel.schemas import Placement
from nts.kernel.solver import SolverTimeout, TimetableSolver
from nts.state import TimetableSet, World
from nts.state.store import touched

from . import words
from .extend import EXTRA
from .read import _at
from .registry import Context, Refusal, Scope, tool
from .talk import number_theirs, waived

TIME_LIMIT = 20.0
MAX_LISTED = 15  # moves listed one by one; past that, a count


@dataclass
class Checked:
    version: str  # the draft version it was solved for
    ok: bool
    sets: list[TimetableSet]


class CheckDraft(BaseModel):
    pass


@tool(Scope.EVALUATE)
def check_draft(ctx: Context, args: CheckDraft) -> dict:
    """Ask the solver what the draft does: whether it can be done, which classes move, who else is affected,
    which wishes cannot be met, or which rules clash. Call it after changing the draft and before submitting."""
    if ctx.draft is None:
        raise Refusal("no_draft", "this episode has no draft")
    base, after = ctx.world, ctx.draft.world
    added = [c for cid, c in after.constraints.items() if cid not in base.constraints]
    removed = [c for cid, c in base.constraints.items() if cid not in after.constraints]
    cancels = cancellations(base, after)
    if not added and not removed and not cancels:
        # a question about an earlier change ("was it approved?") drafts nothing: the refusal says how to answer it
        earlier = "; ".join(ctx.scratch.get("earlier", []))
        raise Refusal("empty_draft", "the draft has no changes yet. If the person only asked something, such as whether "
                      "an earlier change was approved, answer them in plain words with no tool"
                      + (f". What came of the earlier changes: {earlier}" if earlier else "") + ". Do not decline")
    ours = {c.id: n for n, ids in ctx.scratch.get("changes", {}).items() for c in added if c.id in ids}
    # removing or waiving a rule never breaks a timetable
    weeks = set().union(*(touched(after, c) for c in added if not waived(c.id))) | set(cancels)
    if (exams := _exams(ctx, _asked_weeks(ctx, added, cancels), cancels)) is not None:
        ctx.scratch["check"] = Checked(after.version, False, [])
        return exams
    if not weeks:
        ctx.scratch["check"] = Checked(after.version, True, [])
        return {"ok": True, "applies_to": "no timetable changes", "classes_moved": 0, "moves": [],
                "others_affected": [], "not_met": []}

    groups: dict[tuple, list[int | None]] = {}
    for w in weeks:
        key = (frozenset(c.id for c in after.active(w)), w if w in base.timetables or w in cancels else None)
        groups.setdefault(key, []).append(w)

    sets: list[TimetableSet] = []
    moved: dict[str, tuple[Placement, Placement]] = {}
    unmet: set[str] = set()
    for ws in groups.values():
        w = min(ws, key=lambda x: 0 if x is None else x)
        now, skip = base.timetable(w), after.timetable(w)
        assert now is not None and skip is not None
        solver = TimetableSolver(after.instance, after.constraints.values(), week=w, baseline=now.assignment,
                                 skip=skip.cancelled, time_limit=TIME_LIMIT, presolve=False)
        result = solver.solve()
        if result.status == "unknown":
            ctx.scratch["check"] = Checked(after.version, False, [])
            return {"ok": False, "why": "the solver ran out of time; try a smaller change"}
        if not result.ok:
            ctx.scratch["check"] = Checked(after.version, False, [])
            if not args_retry(ctx) and _set_aside(ctx, solver, ours, ws):
                ctx.scratch["retry"] = True
                try:
                    out = check_draft.handler(ctx, args)
                finally:
                    ctx.scratch.pop("retry", None)
                return {**out, "set_aside": ctx.scratch.get("set_aside", [])}
            return _clash(ctx, solver, ours, ws)
        assert result.assignment is not None
        sets += [TimetableSet(week=x, assignment=result.assignment, cancelled=sorted(skip.cancelled)) for x in ws]
        for sid, p in result.assignment.items():
            if now.assignment.get(sid) != p and sid not in moved and sid not in skip.cancelled:
                moved[sid] = (now.assignment[sid], p)
        unmet |= set(result.soft_violations) & set(ours)  # the wishes in this draft that the solver could not meet

    ctx.scratch["check"] = Checked(after.version, True, sets)
    inst = after.instance
    rows = [{"class": _at(inst, inst.session_by_id[sid], a), "now": _at(inst, inst.session_by_id[sid], b)}
            for sid, (a, b) in sorted(moved.items())]
    me = inst.faculty_by_id[ctx.actor].name if ctx.actor in inst.faculty_by_id else None
    others = sorted({r["class"]["teacher"] for r in rows} - {me}) + sorted({g for r in rows for g in r["class"]["sections"]})
    out = {"ok": True, "applies_to": _span(ws for ws in groups.values()), "classes_moved": len(rows),
           "moves": rows[:MAX_LISTED], "others_affected": others,
           "not_met": [words.constraint(inst, after.constraints[c]) for c in sorted(unmet)]}
    if len(rows) > MAX_LISTED:
        out["more_moves"] = len(rows) - MAX_LISTED
    if cancels:
        out["cancelled"] = [{**_at(inst, inst.session_by_id[sid], base.timetable(w).assignment[sid]), "week": w}
                            for w, sids in sorted(cancels.items()) for sid in sorted(sids)]
    return out


def args_retry(ctx: Context) -> bool:
    return bool(ctx.scratch.get("retry"))


def _set_aside(ctx: Context, solver: TimetableSolver, ours: dict[str, int], ws: list[int | None]) -> bool:
    """A firm absence of the requester comes before their own standing rules for their classes (operational or
    preference rules, which their owner may relax), as the request pipeline lets it: a rule of theirs that keeps a class where the absence
    falls ("the practical only on Tuesday 2-5 pm") is set aside for the weeks of the absence, in the draft,
    so the class can move. Only the requester's own rules, about only their own classes, and only for named
    weeks; anything else stays a clash for the model to handle. True: the draft changed, check again."""
    from nts.kernel.schemas import ConstraintType, Tier
    from nts.state import ConstraintAdded, ConstraintRemoved

    weeks = sorted(w for w in ws if w is not None)
    if not weeks or None in ws:
        return False
    try:
        core = solver.core(solver.hard_ids) or []
    except SolverTimeout:
        return False
    after = ctx.state
    inst = after.instance
    absent = [c for c in core if c in ours and after.constraints[c].type == ConstraintType.UNAVAILABLE
              and after.constraints[c].hard and after.constraints[c].scope.faculty == ctx.actor]
    if not absent:
        return False

    def own(c) -> bool:
        s = c.scope
        session_mine = s.session is not None and inst.session_by_id[s.session].faculty == ctx.actor
        course_mine = s.course is not None and all(x.faculty == ctx.actor for x in inst.sessions
                                                   if x.course == s.course)
        return (c.owner == ctx.actor and c.tier >= Tier.OPERATIONAL
                and (session_mine or course_mine or s.faculty == ctx.actor))

    theirs = [after.constraints[c] for c in core if c not in ours]
    if not theirs or not all(own(c) for c in theirs):
        return False
    draft = ctx.draft
    for c in theirs:
        valid = c.valid.model_copy(update={"except_weeks": sorted({*c.valid.except_weeks, *weeks})})
        aside = c.model_copy(update={"id": f"{c.id}~{draft.episode or 'draft'}", "valid": valid,
                                     "source": c.source.model_copy(update={"request": "set aside: the requester is away"})})
        draft.add(ConstraintRemoved(id=c.id))
        draft.add(ConstraintAdded(constraint=aside))
        ctx.scratch.setdefault("set_aside", []).append(
            f"{words.constraint(inst, c)}: set aside in {_span([weeks])}, since you are away then (your own rule)")
    return True


def _asked_weeks(ctx: Context, added: list, cancels: dict[int, set[str]]) -> set[int | None]:
    """The weeks the draft's changes are for: each new rule's from_week to to_week (to the end of term when open,
    every week when it has none), and the weeks of its cancellations. Not the weeks the solver re-solves, which run
    on past the change."""
    n = ctx.world.instance.calendar.weeks
    out: set[int | None] = set(cancels)
    for c in added:
        if waived(c.id):
            continue
        v = c.valid
        out |= set(range(v.from_week or 1, (v.to_week or n) + 1)) - set(v.except_weeks or [])
    return out


def _exams(ctx: Context, weeks: set[int | None], cancels: dict[int, set[str]]) -> dict | None:
    """The examination regulations on a draft for the weeks around the examinations (``nts.exams``): a change in an
    examination week is declined, one in the weeks next to one is escalated (the Controller of Examinations must
    approve it). None: no such week, or the department's regulations do not include them."""
    rules = {r.id: r.text for r in getattr(ctx.handbook, "rules", None) or []}
    extra = any((c.source.rule or "").startswith(EXTRA) for cid, c in ctx.draft.world.constraints.items()
                if cid not in ctx.world.constraints and c.source is not None)
    ruling = exam_ruling(weeks, rules, extra=extra)
    if ruling is None:
        return None
    if ruling.action == "forward":
        if ctx.exams_granted:  # the examination cell has approved it: the change goes ahead like any other
            return None
        ctx.scratch["exams"] = ruling  # the office reads it from the escalation: who the request goes to next
    end = ("decline, telling the person why" if ruling.action == "refuse" else
           "escalate, so the office passes it to the examination cell, and tell the person it was forwarded")
    return {"ok": False, "why": f"{ruling.message} Do not submit or change the weeks yourself: {end}.",
            "rules": ruling.cited}


def cancellations(base: World, after: World) -> dict[int, set[str]]:
    """Week -> the classes the draft cancels (or holds again) there."""
    out: dict[int, set[str]] = {}
    for w, tt in after.timetables.items():
        was = base.timetable(w)
        if w is not None and was is not None and tt.cancelled != was.cancelled:
            out[w] = set(tt.cancelled ^ was.cancelled)
    return out


def _clash(ctx: Context, solver: TimetableSolver, ours: dict[str, int], ws: list[int | None]) -> dict:
    try:
        core = solver.core(solver.hard_ids) or []
    except SolverTimeout:
        core = []
    after = ctx.state
    inst = after.instance
    blocked = [] if None in ws else sorted(w for w in ws if w is not None)  # [] : the whole term

    def by(cid: str) -> dict:
        if cid in ours:
            return {"your_change": ours[cid]}
        owner = after.constraints[cid].owner
        if owner in inst.faculty_by_id and owner != ctx.actor:
            given = sum(e.stakeholder == owner for e in after.concessions)
            return {"set_by": inst.faculty_by_id[owner].name, "number": number_theirs(ctx, cid, blocked),
                    "has_given_way": f"{given} time{'s' * (given != 1)} this term"}
        return {"set_by": "already agreed"}

    rules = [{"rule": words.constraint(inst, after.constraints[c]), **by(c)} for c in core]
    return {"ok": False, "applies_to": _span([ws]),
            "why": "these rules cannot all hold at once" if rules else "the draft cannot be done",
            "clashing": rules,
            "next": "retract or soften (firm=false) one of your changes, ask the owner of a numbered rule to waive it "
                    "(make_offer), or decline or escalate the request"}


def _span(groups) -> str:
    ws = sorted({w for g in groups for w in g}, key=lambda x: 0 if x is None else x)
    if None in ws:
        return "the whole term" + (f" (and weeks {words.joined([str(w) for w in ws if w])})" if len(ws) > 1 else "")
    return f"week {ws[0]}" if len(ws) == 1 else f"weeks {words.joined([str(w) for w in ws])}"


EVALUATE_TOOLS = [check_draft]
