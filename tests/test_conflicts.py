import pytest

from core.conflicts import enumerate_mcs, find_mus
from core.scenarios import uc3_lab_contention
from core.solver import TimetableSolver
from core.validator import verify_timetable

LAB_CONSTRAINTS = ["C-DAS-ROOM", "C-DAS-TIME", "C-KHAN-ROOM", "C-KHAN-TIME"]


@pytest.fixture(scope="module")
def uc3():
    inst, cons = uc3_lab_contention()
    return inst, cons, TimetableSolver(inst, cons, time_limit=10)


def test_uc3_is_infeasible(uc3):
    _, _, solver = uc3
    assert not solver.is_feasible(solver.hard_ids)


def test_uc3_mus_is_the_four_lab_constraints(uc3):
    _, _, solver = uc3
    assert find_mus(solver) == LAB_CONSTRAINTS  # policy rules are not part of it


def test_uc3_mcs_options_are_single_concessions_with_valid_witnesses(uc3):
    inst, cons, solver = uc3
    options = enumerate_mcs(solver, limit=10)
    assert sorted(o.drop[0] for o in options) == LAB_CONSTRAINTS
    assert all(len(o.drop) == 1 and o.cost == 1 for o in options)
    for o in options:
        assert o.witness.ok
        kept = [c for c in cons if c.id not in o.drop]
        assert verify_timetable(inst, o.witness.assignment, kept) == []


def test_costs_order_options(uc3):
    _, _, solver = uc3
    costs = {"C-DAS-ROOM": 9, "C-DAS-TIME": 9, "C-KHAN-ROOM": 9, "C-KHAN-TIME": 2}
    first = enumerate_mcs(solver, costs=costs, limit=1)[0]
    assert first.drop == ["C-KHAN-TIME"]


def test_policy_rules_are_never_offered(uc3):
    _, _, solver = uc3
    for o in enumerate_mcs(solver, limit=10):
        assert not any(i.startswith("P-") for i in o.drop)


def test_feasible_set_has_no_conflict(uc3):
    _, _, solver = uc3
    feasible = [i for i in solver.hard_ids if i != "C-KHAN-TIME"]
    assert enumerate_mcs(solver, feasible) == []
    with pytest.raises(ValueError):
        find_mus(solver, feasible)
