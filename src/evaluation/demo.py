"""End-to-end check of the foundation: ``uv run python -m evaluation.demo``."""

from __future__ import annotations

import argparse

from core.conflicts import enumerate_mcs, find_mus
from core.generator import generate_department
from core.instance import policy_constraints
from core.scenarios import uc3_lab_contention
from core.solver import TimetableSolver
from core.validator import verify_timetable


def department(seed: int, time_limit: float) -> None:
    inst = generate_department(seed=seed)
    cons = policy_constraints(inst)
    print(f"[department] {inst.name}: {len(inst.faculty)} faculty, {len(inst.groups)} groups, "
          f"{len(inst.rooms)} rooms, {len(inst.sessions)} sessions")
    result = TimetableSolver(inst, cons, time_limit=time_limit).solve()
    print(f"  solve: {result.status} in {result.wall_time:.1f}s")
    if result.ok:
        problems = verify_timetable(inst, result.assignment, cons)
        print(f"  independent validator: {'valid' if not problems else problems}")


def uc3() -> None:
    inst, cons = uc3_lab_contention()
    names = {f.id: f.name for f in inst.faculty}
    solver = TimetableSolver(inst, cons, time_limit=10)
    print("\n[UC3] Dr. Khan and Dr. Das both need Lab 2 on Tuesday afternoon")
    print(f"  feasible as requested: {solver.is_feasible(solver.hard_ids)}")
    print(f"  MUS: {find_mus(solver)}")
    print("  solver-verified compromise options (MCS):")
    for o in enumerate_mcs(solver):
        c = solver.constraints[o.drop[0]]
        moved = {s: p for s, p in o.witness.assignment.items() if s.endswith("-P")}
        where = ", ".join(f"{s} {p.day} slot {p.slot} {p.room}" for s, p in sorted(moved.items()))
        print(f"   - {names[c.owner]} concedes {o.drop} (cost {o.cost}): {where}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--time-limit", type=float, default=60.0)
    args = parser.parse_args()
    department(args.seed, args.time_limit)
    uc3()


if __name__ == "__main__":
    main()
