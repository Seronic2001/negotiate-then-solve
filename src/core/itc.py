"""ITC-2007 Track 3 (curriculum-based course timetabling) instances.

Reads the ``.ctt`` format (Di Gaspero, McCollum and Schaerf, 2007) and writes
solutions in the competition's ``.sol`` format so they can be checked with
the official validator. The comp01-comp21 instances are distributed through
the CB-CTT benchmark portal maintained by the University of Udine.

Mapping onto our model:

* each course with ``n`` lectures becomes ``n`` one-slot lecture sessions;
* each teacher becomes a faculty member (teacher conflicts);
* each curriculum becomes a student group (curriculum conflicts);
* unavailability lines become hard Tier 2 constraints, one per course and day;
* room capacity is a *soft* penalty in ITC-2007, so by default it becomes a
  soft ``require_room`` constraint per course (weight 1 per lecture in a room
  that is too small; ITC weighs by the number of excess students instead).

The ITC soft constraints for minimum working days, curriculum compactness and
room stability are not modelled.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

from .instance import (
    Calendar,
    Faculty,
    Group,
    Instance,
    Policy,
    Room,
    RoomType,
    Session,
    SessionKind,
)
from .schemas import (
    DAYS,
    Constraint,
    ConstraintType,
    Placement,
    RoomRequirement,
    Scope,
    Source,
    Tier,
    When,
)

_SECTIONS = ("COURSES:", "ROOMS:", "CURRICULA:", "UNAVAILABILITY_CONSTRAINTS:")


class CttFormatError(ValueError):
    pass


def load_ctt(source: str | Path, *, capacity: str = "soft") -> tuple[Instance, list[Constraint]]:
    """Parse a ``.ctt`` file (path) or its text.

    ``capacity`` is ``"soft"`` (ITC semantics) or ``"hard"`` (our department
    semantics: a session never goes into a room that is too small).
    """
    if capacity not in ("soft", "hard"):
        raise ValueError("capacity must be 'soft' or 'hard'")
    text = Path(source).read_text() if isinstance(source, Path) or "\n" not in source else source

    header: dict[str, str] = {}
    body: dict[str, list[list[str]]] = defaultdict(list)
    section: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "END.":
            break
        if line in _SECTIONS:
            section = line
        elif section is None:
            key, _, value = line.partition(":")
            header[key.strip()] = value.strip()
        else:
            body[section].append(line.split())

    try:
        n_days = int(header["Days"])
        periods = int(header["Periods_per_day"])
    except KeyError as e:
        raise CttFormatError(f"missing header field {e}") from None
    if n_days > len(DAYS):
        raise CttFormatError(f"{n_days} days is more than a week")

    rooms = [Room(id=r, name=r, capacity=int(cap), type=RoomType.LECTURE) for r, cap in body["ROOMS:"]]

    curricula: dict[str, list[str]] = {}
    for row in body["CURRICULA:"]:
        cid, n, members = row[0], int(row[1]), row[2:]
        if len(members) != n:
            raise CttFormatError(f"curriculum {cid} lists {len(members)} courses, header says {n}")
        curricula[cid] = members
    groups_of: dict[str, list[str]] = defaultdict(list)
    for cid, members in curricula.items():
        for course in members:
            groups_of[course].append(cid)

    teachers: dict[str, Faculty] = {}
    sessions: list[Session] = []
    students: dict[str, int] = {}
    for row in body["COURSES:"]:
        course, teacher, lectures, _min_days, n_students = row[0], row[1], int(row[2]), row[3], int(row[4])
        teachers.setdefault(teacher, Faculty(id=teacher, name=teacher, department="ITC"))
        students[course] = n_students
        for k in range(lectures):
            sessions.append(
                Session(
                    id=f"{course}-{k}",
                    course=course,
                    kind=SessionKind.LECTURE,
                    faculty=teacher,
                    groups=groups_of.get(course, []),
                    size=n_students if capacity == "hard" else 0,
                )
            )

    instance = Instance(
        name=header.get("Name", "itc"),
        calendar=Calendar(days=list(DAYS[:n_days]), slots_per_day=periods, lunch_slot=None),
        rooms=rooms,
        faculty=list(teachers.values()),
        groups=[Group(id=c, name=c, size=0) for c in curricula],
        sessions=sessions,
        policy=Policy(max_consecutive=None, lunch_break=False),
    )

    unavailable: dict[tuple[str, int], list[int]] = defaultdict(list)
    for course, day, period in body["UNAVAILABILITY_CONSTRAINTS:"]:
        unavailable[(course, int(day))].append(int(period))
    constraints = [
        Constraint(
            id=f"ITC-UNAV-{course}-{day}",
            type=ConstraintType.UNAVAILABLE,
            hard=True,
            tier=Tier.COMMITMENT,
            scope=Scope(course=course),
            when=When(days=[DAYS[day]], slots=sorted(slots)),
            source=Source(rule="ITC-2007 unavailability"),
        )
        for (course, day), slots in sorted(unavailable.items())
    ]
    if capacity == "soft":
        for course, n in students.items():
            fits = [r.id for r in rooms if r.capacity >= n]
            if len(fits) < len(rooms):
                constraints.append(
                    Constraint(
                        id=f"ITC-CAP-{course}",
                        type=ConstraintType.REQUIRE_ROOM,
                        hard=False,
                        tier=Tier.PREFERENCE,
                        scope=Scope(course=course),
                        room=RoomRequirement(rooms=fits),
                        source=Source(rule="ITC-2007 room capacity (soft)"),
                    )
                )
    return instance, constraints


def to_ctt_solution(instance: Instance, assignment: Mapping[str, Placement]) -> str:
    """One ``<course> <room> <day> <period>`` line per lecture."""
    lines = []
    for s in instance.sessions:
        p = assignment[s.id]
        lines.append(f"{s.course} {p.room} {instance.day_index(p.day)} {p.slot}")
    return "\n".join(lines) + "\n"
