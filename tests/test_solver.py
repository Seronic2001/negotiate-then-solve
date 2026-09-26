import pytest

from nts.generator import generate_department
from nts.instance import policy_constraints
from nts.schemas import Constraint, ConstraintType, Scope, Tier, When
from nts.solver import TimetableSolver
from nts.validator import validate_constraint, verify_timetable


@pytest.fixture(scope="module")
def small():
    inst = generate_department(seed=1, n_faculty=8, n_groups=3, n_lecture_rooms=4, n_labs=3)
    return inst, policy_constraints(inst)


@pytest.fixture(scope="module")
def base(small):
    inst, cons = small
    result = TimetableSolver(inst, cons, time_limit=20).solve()
    assert result.ok
    return result


def test_base_timetable_is_valid(small, base):
    inst, cons = small
    assert set(base.assignment) == {s.id for s in inst.sessions}
    assert verify_timetable(inst, base.assignment, cons) == []


def test_validator_catches_double_booking(small, base):
    inst, _ = small
    broken = dict(base.assignment)
    a, b = [s.id for s in inst.sessions if s.duration == 1][:2]
    broken[b] = broken[a]
    problems = verify_timetable(inst, broken)
    assert any("double-booked" in p for p in problems)


def test_week_scoped_unavailability_and_minimal_repair(small, base):
    """UC2 shape: a faculty member is away Tue-Thu in week 7 only."""
    inst, cons = small
    fac = inst.sessions[0].faculty
    away = Constraint(
        id="C-AWAY", type=ConstraintType.UNAVAILABLE, hard=True, tier=Tier.VERIFIED_UNAVAILABILITY,
        owner=fac, scope=Scope(faculty=fac), when=When(days=["Tue", "Wed", "Thu"], weeks=[7]),
    )
    assert validate_constraint(away, inst) == []

    week7 = TimetableSolver(inst, cons + [away], week=7, baseline=base.assignment, time_limit=20).solve()
    assert week7.ok
    assert verify_timetable(inst, week7.assignment, cons + [away], week=7) == []
    teaching = [s for s in inst.sessions if s.faculty == fac]
    assert all(week7.assignment[s.id].day not in ("Tue", "Wed", "Thu") for s in teaching)
    # Repair mode stays local: the forced moves plus at most a short cascade
    # (a displaced session can bump another), not a rebuild.
    must_move = sum(base.assignment[s.id].day in ("Tue", "Wed", "Thu") for s in teaching)
    assert week7.status == "optimal"
    assert must_move <= week7.moved <= must_move + 3

    # The base timetable ignores the week-7 constraint.
    assert TimetableSolver(inst, cons + [away]).hard_ids == [c.id for c in cons]


def test_soft_preference_is_honoured_when_possible(small):
    inst, cons = small
    fac = inst.sessions[0].faculty
    pref = Constraint(
        id="C-LATE", type=ConstraintType.AVOID, hard=False, tier=Tier.PREFERENCE,
        owner=fac, scope=Scope(faculty=fac), when=When(days=["Mon", "Wed"], slots=[0, 1]),
    )
    result = TimetableSolver(inst, cons + [pref], time_limit=20).solve()
    assert result.ok
    assert "C-LATE" not in result.soft_violations


def test_lexicographic_keeps_lower_tier(small):
    """A Tier 3 unavailability beats a clashing Tier 4 requirement."""
    inst, cons = small
    s = next(x for x in inst.sessions if x.duration == 1)
    t3 = Constraint(id="C-T3", type=ConstraintType.UNAVAILABLE, hard=True, tier=Tier.VERIFIED_UNAVAILABILITY,
                    scope=Scope(session=s.id), when=When(days=["Mon"]))
    t4 = Constraint(id="C-T4", type=ConstraintType.PREFER, hard=True, tier=Tier.OPERATIONAL,
                    scope=Scope(session=s.id), when=When(days=["Mon"]))
    result = TimetableSolver(inst, cons + [t3, t4], time_limit=20).solve_lexicographic()
    assert result.ok
    assert "C-T3" in result.enforced
    assert result.relaxed == ["C-T4"]


def test_unknown_references_rejected(small):
    inst, _ = small
    c = Constraint(id="C-X", type=ConstraintType.UNAVAILABLE, hard=True, tier=Tier.VERIFIED_UNAVAILABILITY,
                   scope=Scope(faculty="F-999"), when=When(days=["Sat"], slots=[12], weeks=[40]))
    errors = validate_constraint(c, inst)
    assert len(errors) == 4


@pytest.mark.slow
def test_full_department_solves():
    inst = generate_department(seed=0)
    cons = policy_constraints(inst)
    result = TimetableSolver(inst, cons, time_limit=120).solve()
    assert result.ok
    assert verify_timetable(inst, result.assignment, cons) == []
