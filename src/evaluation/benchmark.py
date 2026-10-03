"""Negotiation scenarios with planted conflicts and oracle outcomes
(proposal Section 12.1: 60 scenarios).

    uv run python -m evaluation.benchmark          # writes data/scenarios.jsonl

Each scenario is a small department (four teaching faculty, three sections,
two lecture rooms and a few labs) with a baseline timetable, the constraints
that arrived since (``planted``), and hidden stakeholder profiles. Kinds:

* ``contention`` (UC3): two practicals need the one lab with their equipment
  in the same afternoon; sometimes an equivalent lab exists (auto-substitute);
* ``deadlock``: contention where nobody is flexible (must escalate);
* ``squeeze`` (Tier 3 vs 4): a verified unavailability pins one practical
  into the slot another faculty member demands;
* ``capacity`` (UC5): a lab outage plus an exam block leave too few lab
  slots; only Tier 0-2 changes help (must escalate to the coordinator);
* ``tradeoff``: feasible, but two soft preferences compete (auto-relax);
* ``policy`` (UC4): a demand that breaks the lunch break or the
  consecutive-hours rule (the requester must move, or the Dean decides).

Each scenario is assigned one stakeholder policy family (strict, flexible,
cost-sensitive, history-sensitive; balanced within each kind) that reshapes
the hidden profiles and makes replies stochastic (``agents.simulators``).

The oracle (the upper bound) knows every profile and tries all combinations of
the flexibility they hide. It optimises the same published policy and
objective as the negotiator (proposal Section 13.2): lexicographically, the
constraints given up per tier (Tier 3 first), then the option cost
``sum pi_k + l1 moved + l2 dGini`` from ``PriorityModel.option_cost``, with
the scenario's own concession history. Ties go to fewer stakeholders asked.
``objective`` scores any outcome the same way, so systems are compared with
the oracle on one scale.
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, Field

from agents.ledger import ConcessionLedger
from agents.priority import PriorityModel
from agents.simulators import FAMILIES, Family, Profile, Simulator, Window, apply_family
from core.generator import SURNAMES
from core.instance import (
    Faculty,
    Group,
    Instance,
    Room,
    RoomType,
    Session,
    SessionKind,
    policy_constraints,
)
from core.schemas import (
    ConcessionEntry,
    Constraint,
    ConstraintType,
    Justification,
    Placement,
    Role,
    RoomRequirement,
    Scope,
    Source,
    Tier,
    Validity,
    When,
)
from core.solver import TimetableSolver

AFTERNOON = [5, 6, 7]
MORNING = [0, 1, 2, 3]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
COURSES = ["Machine Learning", "Computer Networks", "Operating Systems", "Database Systems",
           "Digital Logic", "Compiler Design", "Algorithms", "Computer Graphics"]


SEMESTER = "2026-1"  # the semester scenarios are negotiated in
SCORED_TIERS = (Tier.VERIFIED_UNAVAILABILITY, Tier.OPERATIONAL, Tier.PREFERENCE)


class OracleOutcome(BaseModel):
    status: str  # feasible | agree | escalate
    moved: int = 0
    concessions: int = 0  # stakeholders who give something up
    choice: dict[str, str] = Field(default_factory=dict)  # owner -> keep | window:i | room
    relaxed: list[str] = Field(default_factory=list)  # constraints given up or weakened
    tiers: list[int] = Field(default_factory=list)  # constraints given up in Tiers 3, 4, 5
    objective: float | None = None  # option cost of the outcome (see ``objective``)


class Scenario(BaseModel):
    id: str
    kind: str
    seed: int
    instance: Instance
    base: list[Constraint]  # policy and constraints already in force
    planted: list[Constraint]  # what arrived since
    baseline: dict[str, Placement]
    week: int | None = None
    profiles: list[Profile]
    ledger: list[ConcessionEntry] = Field(default_factory=list)
    raw_requests: dict[str, str] = Field(default_factory=dict)
    private: list[str] = Field(default_factory=list)
    family: Family | None = None  # stakeholder policy family; None: deterministic legacy profiles
    oracle: OracleOutcome | None = None

    @property
    def constraints(self) -> list[Constraint]:
        return [*self.base, *self.planted]

    @property
    def expected(self) -> str:
        return self.oracle.status if self.oracle else "?"


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def _department(rng: random.Random, name: str, labs: list[Room]) -> Instance:
    names = rng.sample(SURNAMES, 5)
    faculty = [Faculty(id="F-300", name=f"Dr. {names[0]}", department="CSE", role=Role.HOD)]
    faculty += [Faculty(id=f"F-30{i}", name=f"Dr. {names[i]}", department="CSE", reports_to="F-300")
                for i in range(1, 5)]
    groups = [Group(id=f"G-{c}", name=f"CSE 3{c}", size=rng.randint(40, 60)) for c in "ABC"]
    courses = rng.sample(COURSES, 4)
    sessions = []
    for i in range(4):
        f, g = faculty[i + 1].id, groups[i % 3].id
        for k in (1, 2):
            sessions.append(Session(id=f"C{i + 1}-L{k}", course=f"C{i + 1}", kind=SessionKind.LECTURE,
                                    faculty=f, groups=[g]))
    rooms = [Room(id="R-101", name="Room 101", capacity=80, type=RoomType.LECTURE),
             Room(id="R-102", name="Room 102", capacity=80, type=RoomType.LECTURE), *labs]
    inst = Instance(name=name, rooms=rooms, faculty=faculty, groups=groups, sessions=sessions,
                    course_titles={f"C{i + 1}": courses[i] for i in range(4)})
    return inst


def _practical(inst: Instance, fac_index: int, duration: int = 2, equipment: list[str] | None = None) -> str:
    sid = f"C{fac_index}-P"
    inst.sessions.append(Session(id=sid, course=f"C{fac_index}", kind=SessionKind.PRACTICAL,
                                 faculty=f"F-30{fac_index}", groups=[f"G-{'ABC'[(fac_index - 1) % 3]}"],
                                 duration=duration, room_type=RoomType.LAB, equipment=equipment or []))
    return sid


def _lab(id_: str, n: int, equipment: list[str]) -> Room:
    return Room(id=id_, name=f"Lab {n}", capacity=60, type=RoomType.LAB, equipment=equipment)


def _c(cid: str, owner: str | None, tier: Tier, ctype: ConstraintType, *, hard: bool = True,
       scope: Scope, when: When | None = None, room: RoomRequirement | None = None,
       just: Justification = Justification.STATED, request: str | None = None,
       valid: Validity | None = None, weight: float | None = None) -> Constraint:
    return Constraint(id=cid, type=ctype, hard=hard, tier=tier, owner=owner, scope=scope, when=when or When(),
                      room=room, justification=just, source=Source(request=request),
                      valid=valid or Validity(), weight=weight)


def _names(inst: Instance) -> dict[str, str]:
    return {f.id: f.name for f in inst.faculty}


def _title(inst: Instance, sid: str) -> str:
    s = next(x for x in inst.sessions if x.id == sid)
    return inst.course_title(s.course)


# ---------------------------------------------------------------------------
# Scenario kinds
# ---------------------------------------------------------------------------


def contention(rng: random.Random, sid: str, *, substitute: bool = False, deadlock: bool = False) -> dict:
    labs = [_lab("L-1", 1, ["gpu", "routers"]), _lab("L-2", 2, []), _lab("L-3", 3, ["electronics"])]
    if substitute:
        labs.append(_lab("L-4", 4, ["gpu"]))
    inst = _department(rng, sid, labs)
    a, b = rng.sample([1, 2, 3, 4], 2)
    pa, pb = _practical(inst, a), _practical(inst, b)
    day = rng.choice(DAYS)
    names = _names(inst)
    fa, fb = f"F-30{a}", f"F-30{b}"
    planted = [
        _c("C-A-ROOM", fa, Tier.OPERATIONAL, ConstraintType.REQUIRE_ROOM, scope=Scope(session=pa),
           room=RoomRequirement(equipment=["gpu"]), request="R-A"),
        _c("C-A-TIME", fa, Tier.OPERATIONAL, ConstraintType.PREFER, scope=Scope(session=pa),
           when=When(days=[day], slots=AFTERNOON), request="R-A"),
        _c("C-B-ROOM", fb, Tier.OPERATIONAL, ConstraintType.REQUIRE_ROOM, scope=Scope(session=pb),
           room=RoomRequirement(equipment=["routers"]), request="R-B"),
        _c("C-B-TIME", fb, Tier.OPERATIONAL, ConstraintType.PREFER, scope=Scope(session=pb),
           when=When(days=[day], slots=AFTERNOON), request="R-B"),
    ]
    other = [d for d in DAYS if d != day]
    profiles = []
    for owner, need in ((fa, "gpu"), (fb, "routers")):
        if deadlock:
            profiles.append(Profile(owner=owner, needs=[need]))
            continue
        flexible = rng.random() < 0.75
        windows = [Window(days=rng.sample(other, rng.randint(1, 2)), slots=rng.choice([AFTERNOON, MORNING]))] \
            if flexible else []
        profiles.append(Profile(owner=owner, needs=[need], windows=windows, reveal=rng.random() < 0.6))
    if not deadlock and not any(p.windows for p in profiles):
        profiles[rng.randrange(2)].windows = [Window(days=[rng.choice(other)], slots=AFTERNOON)]
    ledger = []
    if rng.random() < 0.5:  # one of them conceded last semester
        who = rng.choice([fa, fb])
        ledger.append(ConcessionEntry(stakeholder=who, constraint_id="PAST", semester="2025-2"))
    full = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday"}[day]
    raw = {"R-A": f"My {_title(inst, pa)} practical needs the GPU machines, and it has to be on {full} "
                  f"afternoon. {names[fa]}",
           "R-B": f"The {_title(inst, pb)} lab needs routers; {full} afternoon is the only time I can do. "
                  f"{names[fb]}"}
    return {"inst": inst, "planted": planted, "profiles": profiles, "ledger": ledger, "raw": raw}


def squeeze(rng: random.Random, sid: str) -> dict:
    inst = _department(rng, sid, [_lab("L-1", 1, ["gpu", "routers"]), _lab("L-2", 2, [])])
    a, b = rng.sample([1, 2, 3, 4], 2)
    pa, _pb = _practical(inst, a), _practical(inst, b, equipment=["routers"])
    inst.sessions = [s for s in inst.sessions if not (s.faculty == f"F-30{b}" and s.kind == SessionKind.LECTURE)]
    day = rng.choice(DAYS)
    fa, fb = f"F-30{a}", f"F-30{b}"
    reason = rng.choice(["clinical duty", "a hospital appointment", "family care"])
    planted = [
        _c("C-B-UNAV", fb, Tier.VERIFIED_UNAVAILABILITY, ConstraintType.UNAVAILABLE, scope=Scope(faculty=fb),
           when=When(days=[d for d in DAYS if d != day]), just=Justification.VERIFIED, request="R-B"),
        _c("C-B-UNAV-AM", fb, Tier.VERIFIED_UNAVAILABILITY, ConstraintType.UNAVAILABLE, scope=Scope(faculty=fb),
           when=When(days=[day], slots=MORNING), just=Justification.VERIFIED, request="R-B"),
        _c("C-A-ROOM", fa, Tier.OPERATIONAL, ConstraintType.REQUIRE_ROOM, scope=Scope(session=pa),
           room=RoomRequirement(equipment=["gpu"]), request="R-A"),
        _c("C-A-TIME", fa, Tier.OPERATIONAL, ConstraintType.PREFER, scope=Scope(session=pa),
           when=When(days=[day], slots=AFTERNOON), request="R-A"),
    ]
    other = [d for d in DAYS if d != day]
    profiles = [Profile(owner=fa, needs=["gpu"], windows=[Window(days=rng.sample(other, 2), slots=AFTERNOON)],
                        reveal=rng.random() < 0.7),
                Profile(owner=fb, needs=["routers"])]
    names = _names(inst)
    full = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday"}[day]
    raw = {"R-B": f"Because of {reason} I can only teach on {full} afternoons this semester. {names[fb]}",
           "R-A": f"I need my {_title(inst, pa)} practical on {full} afternoon in the GPU lab. {names[fa]}"}
    return {"inst": inst, "planted": planted, "profiles": profiles, "raw": raw, "private": [reason]}


def capacity(rng: random.Random, sid: str) -> dict:
    inst = _department(rng, sid, [_lab("L-1", 1, ["gpu"]), _lab("L-2", 2, ["gpu"])])
    for i in range(1, 5):
        _practical(inst, i, duration=3, equipment=["gpu"])
    # two more 3-hour gpu practicals for extra sections, taught by faculty 1 and 2
    for i, g in ((1, "G-B"), (2, "G-C")):
        inst.sessions.append(Session(id=f"C{i}-P2", course=f"C{i}", kind=SessionKind.PRACTICAL,
                                     faculty=f"F-30{i}", groups=[g], duration=3, room_type=RoomType.LAB,
                                     equipment=["gpu"]))
    week = rng.randint(4, 12)
    blocked = rng.sample(DAYS, 3)
    planted = [
        _c("C-OUTAGE", "S-LAB", Tier.PHYSICAL, ConstraintType.UNAVAILABLE, scope=Scope(room="L-1"),
           when=When(weeks=[week]), valid=Validity(from_week=week, to_week=week), request="R-LAB"),
        _c("C-EXAM", None, Tier.COMMITMENT, ConstraintType.UNAVAILABLE, scope=Scope(room="L-2"),
           when=When(days=blocked, weeks=[week]), valid=Validity(from_week=week, to_week=week),
           request="R-EXAM"),
    ]
    raw = {"R-LAB": f"Lab 1 is closed for maintenance in week {week}.",
           "R-EXAM": f"Lab 2 is reserved for lab exams on {', '.join(blocked)} of week {week}."}
    return {"inst": inst, "planted": planted, "profiles": [], "raw": raw, "week": week}


def tradeoff(rng: random.Random, sid: str) -> dict:
    inst = _department(rng, sid, [_lab("L-1", 1, [])])
    # faculty 1 and 4 teach the same section (G-A): four lectures, two wished-for slots
    day = rng.choice(DAYS)
    slots = rng.choice([[0, 1], [5, 6]])
    planted = [
        _c(f"C-{f}-PREF", f"F-30{f}", Tier.PREFERENCE, ConstraintType.PREFER, hard=False,
           scope=Scope(faculty=f"F-30{f}"), when=When(days=[day], slots=slots), request=f"R-{f}")
        for f in (1, 4)
    ]
    profiles = [Profile(owner="F-301"), Profile(owner="F-304")]
    return {"inst": inst, "planted": planted, "profiles": profiles, "raw": {}}


def policy(rng: random.Random, sid: str) -> dict:
    inst = _department(rng, sid, [_lab("L-1", 1, [])])
    a = rng.randint(1, 4)
    fa = f"F-30{a}"
    day = rng.choice(DAYS)
    other = [d for d in DAYS if d != day]
    if rng.random() < 0.5:
        lecture = f"C{a}-L1"
        planted = [_c("C-A-LUNCH", fa, Tier.OPERATIONAL, ConstraintType.PREFER, scope=Scope(session=lecture),
                      when=When(days=[day], slots=[4]), request="R-A")]
        raw = {"R-A": f"Please schedule my {_title(inst, lecture)} lecture at 1 pm on {day}; it's the only time."}
        windows = [Window(days=[day], slots=[5, 6, 7])]
    else:
        for k in (3, 4):  # four lectures in total
            inst.sessions.append(Session(id=f"C{a}-L{k}", course=f"C{a}", kind=SessionKind.LECTURE,
                                         faculty=fa, groups=[f"G-{'ABC'[(a - 1) % 3]}"]))
        planted = [_c("C-A-BLOCK", fa, Tier.OPERATIONAL, ConstraintType.PREFER, scope=Scope(faculty=fa),
                      when=When(days=[day], slots=[0, 1, 2, 3]), request="R-A")]
        raw = {"R-A": f"Put all 4 of my lectures back-to-back on {day} morning."}
        windows = [Window(days=[day, rng.choice(other)], slots=[0, 1, 2, 3, 5, 6, 7])]
    flexible = rng.random() < 0.7
    profiles = [Profile(owner=fa, windows=windows if flexible else [], reveal=True)]
    return {"inst": inst, "planted": planted, "profiles": profiles, "raw": raw}


# ---------------------------------------------------------------------------
# Assembly and the oracle
# ---------------------------------------------------------------------------

MIX = ([("contention", {})] * 16 + [("contention", {"substitute": True})] * 4
       + [("deadlock", {})] * 6 + [("squeeze", {})] * 10 + [("capacity", {})] * 8
       + [("tradeoff", {})] * 8 + [("policy", {})] * 8)
BUILDERS = {"contention": contention, "deadlock": lambda r, s: contention(r, s, deadlock=True),
            "squeeze": squeeze, "capacity": capacity, "tradeoff": tradeoff, "policy": policy}


def _flex_options(sc: Scenario) -> dict[str, list[tuple[str, list[Constraint], list[str]]]]:
    """Per owner: (label, constraints to add, constraint ids to remove)."""
    out = {}
    for p in sc.profiles:
        own = [c for c in sc.planted if c.owner == p.owner and c.hard]
        options = [("keep", [], [])]
        if p.responsive:
            times = [c for c in own if c.type == ConstraintType.PREFER]
            for i, w in enumerate(p.windows):
                add = [c.model_copy(update={"id": f"{c.id}-W{i}", "when": When(
                    days=w.days or c.when.days, slots=w.slots or c.when.slots, weeks=c.when.weeks)}) for c in times]
                options.append((f"window:{i}", add, [c.id for c in times]))
            if p.room_flexible:
                rooms = [c.id for c in own if c.type == ConstraintType.REQUIRE_ROOM]
                if rooms:
                    options.append(("room", [], rooms))
        out[p.owner] = options
    return out


_SUFFIX = re.compile(r"(-[NW]\d+)+$")  # negotiated (-N3) and oracle (-W0) replacements


def original_ids(sc: Scenario, relaxed: Iterable[str]) -> list[str]:
    """The scenario's own constraints behind relaxed IDs: a counter-offer
    replaces C-A-TIME with C-A-TIME-N2, and relaxing that gives up C-A-TIME."""
    known = {c.id for c in sc.constraints}
    out: list[str] = []
    for cid in relaxed:
        orig = _SUFFIX.sub("", cid)
        if orig in known and orig not in out:
            out.append(orig)
    return out


def stakeholders(sc: Scenario) -> list[str]:
    return sorted({s.faculty for s in sc.instance.sessions})


def objective(sc: Scenario, relaxed: Iterable[str], moved: int) -> tuple[list[int], float]:
    """The oracle objective J for an outcome that gave up ``relaxed`` and moved
    ``moved`` sessions: (constraints given up in Tiers 3, 4, 5; option cost),
    compared lexicographically. It uses the published default weights and the
    scenario's own concession history, the same for every system."""
    by_id = {c.id: c for c in sc.constraints}
    given = [by_id[i] for i in original_ids(sc, relaxed)]
    pm = PriorityModel(sc.instance, ledger=ConcessionLedger(sc.ledger), semester=SEMESTER, baseline=sc.baseline)
    tiers = [sum(1 for c in given if c.tier == t) for t in SCORED_TIERS]
    return tiers, pm.option_cost(given, moved, stakeholders(sc))


def compute_oracle(sc: Scenario, time_limit: float = 20.0) -> OracleOutcome:
    base = {c.id: c for c in sc.constraints}
    solver = TimetableSolver(sc.instance, base.values(), week=sc.week, baseline=sc.baseline, time_limit=time_limit)
    if solver.is_feasible(solver.hard_ids):
        r = solver.solve()
        return OracleOutcome(status="feasible", moved=r.moved or 0)
    flex = _flex_options(sc)
    best: OracleOutcome | None = None
    best_key = None
    owners = list(flex)
    for combo in itertools.product(*(flex[o] for o in owners)):
        changed = sum(label != "keep" for label, _, _ in combo)
        if changed == 0:
            continue
        cons = dict(base)
        removed: list[str] = []
        for _, add, remove in combo:
            for i in remove:
                cons.pop(i, None)
                removed.append(i)
            for c in add:
                cons[c.id] = c
        r = TimetableSolver(sc.instance, cons.values(), week=sc.week, baseline=sc.baseline,
                            time_limit=time_limit).solve()
        if not r.ok:
            continue
        moved = r.moved or 0
        tiers, cost = objective(sc, removed, moved)
        key = (tiers, round(cost, 9), changed)
        if best_key is None or key < best_key:
            best_key = key
            best = OracleOutcome(status="agree", moved=moved, concessions=changed, relaxed=removed, tiers=tiers,
                                 objective=cost,
                                 choice={o: label for o, (label, _, _) in zip(owners, combo, strict=True)})
    return best or OracleOutcome(status="escalate")


def simulators(sc: Scenario, *, client=None, structured: bool = True, run_seed: int = 0) -> dict[str, Simulator]:
    """One simulator per hidden profile. Family profiles draw refusals and
    silences from a stream seeded by the scenario, the owner and the run seed,
    so every system meets the same stakeholders within a run."""
    return {p.owner: Simulator(sc.instance, p, client=client, structured=structured,
                               rng=random.Random(f"{sc.seed}:{p.owner}:{run_seed}") if p.family else None)
            for p in sc.profiles}


def _with_family(parts: dict, family: Family) -> list[Profile]:
    inst: Instance = parts["inst"]
    past = {e.stakeholder for e in parts.get("ledger", [])}
    out = []
    for p in parts["profiles"]:
        stated = sorted({s for c in parts["planted"] if c.owner == p.owner and c.type == ConstraintType.PREFER
                         for s in (c.when.slots or [])})
        out.append(apply_family(p, family, stated_slots=stated or None,
                                all_slots=list(range(inst.calendar.slots_per_day)),
                                conceded_recently=p.owner in past))
    return out


def build(kind: str, index: int, seed: int, family: Family | None = None, **kw) -> Scenario:
    rng = random.Random(seed)
    sid = f"S-{index:03d}-{kind}"
    parts = contention(rng, sid, **kw) if kind == "contention" else BUILDERS[kind](rng, sid)
    inst: Instance = parts["inst"]
    base = policy_constraints(inst)
    week = parts.get("week")
    baseline = TimetableSolver(inst, base, time_limit=20).solve()
    if not baseline.ok:
        raise RuntimeError(f"{sid}: base instance infeasible")
    profiles = _with_family(parts, family) if family else parts["profiles"]
    sc = Scenario(id=sid, kind=kind if not kw.get("substitute") else "substitute", seed=seed, instance=inst,
                  base=base, planted=parts["planted"], baseline=baseline.assignment, week=week,
                  profiles=profiles, ledger=parts.get("ledger", []), raw_requests=parts["raw"],
                  private=parts.get("private", []), family=family)
    sc.oracle = compute_oracle(sc)
    return sc


def generate(seed: int = 0, families: bool = True) -> list[Scenario]:
    """The 60 scenarios. With ``families``, each kind's scenarios cycle through
    the four stakeholder policy families, so every family meets every kind."""
    rng = random.Random(seed)
    seen: Counter[str] = Counter()
    out = []
    for i, (kind, kw) in enumerate(MIX, 1):
        variant = "substitute" if kw.get("substitute") else kind
        family = FAMILIES[seen[variant] % len(FAMILIES)] if families else None
        seen[variant] += 1
        out.append(build(kind, i, rng.randrange(10**9), family=family, **kw))
    return out


def save(scenarios: list[Scenario], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for sc in scenarios:
            f.write(sc.model_dump_json() + "\n")


def load(path: Path) -> list[Scenario]:
    return [Scenario.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=Path("data/scenarios.jsonl"))
    ap.add_argument("--no-families", action="store_true",
                    help="deterministic legacy stakeholders instead of the four policy families")
    args = ap.parse_args()
    scenarios = generate(args.seed, families=not args.no_families)
    save(scenarios, args.out)

    print(f"wrote {len(scenarios)} scenarios to {args.out}")
    print(json.dumps(Counter(f"{s.kind}:{s.expected}" for s in scenarios), indent=1))
    print(json.dumps(Counter(f"{s.family}:{s.expected}" for s in scenarios), indent=1))


if __name__ == "__main__":
    main()
