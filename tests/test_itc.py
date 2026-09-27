import pytest

from core.itc import CttFormatError, load_ctt, to_ctt_solution
from core.solver import TimetableSolver
from core.validator import verify_timetable

# The "Toy" instance from the ITC-2007 Track 3 specification.
TOY = """Name: Toy
Courses: 4
Rooms: 3
Days: 5
Periods_per_day: 4
Curricula: 2
Constraints: 8

COURSES:
SceCosC Ocra 3 3 30
ArcTec Indaco 3 2 42
TecCos Rosa 5 4 40
Geotec Scarlatti 5 4 18

ROOMS:
A 32
B 50
C 40

CURRICULA:
Cur1 3 SceCosC ArcTec TecCos
Cur2 2 TecCos Geotec

UNAVAILABILITY_CONSTRAINTS:
TecCos 2 0
TecCos 2 1
TecCos 3 2
TecCos 3 3
ArcTec 4 0
ArcTec 4 1
ArcTec 4 2
ArcTec 4 3

END.
"""


def test_toy_structure():
    inst, cons = load_ctt(TOY)
    assert inst.calendar.days == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    assert inst.calendar.slots_per_day == 4
    assert len(inst.sessions) == 3 + 3 + 5 + 5
    assert {s.faculty for s in inst.sessions} == {"Ocra", "Indaco", "Rosa", "Scarlatti"}
    tec = next(s for s in inst.sessions if s.course == "TecCos")
    assert sorted(tec.groups) == ["Cur1", "Cur2"]  # shared course links both curricula
    unav = {c.id: c for c in cons if c.id.startswith("ITC-UNAV")}
    assert unav["ITC-UNAV-TecCos-2"].when.slots == [0, 1]
    assert unav["ITC-UNAV-ArcTec-4"].when.days == ["Fri"]


@pytest.mark.parametrize("capacity", ["soft", "hard"])
def test_toy_solves_and_respects_hard_rules(capacity):
    inst, cons = load_ctt(TOY, capacity=capacity)
    result = TimetableSolver(inst, cons, time_limit=10).solve()
    assert result.ok
    assert verify_timetable(inst, result.assignment, cons) == []
    assert result.soft_violations == {}  # the toy fits every course in a big enough room
    for sid, p in result.assignment.items():
        room = inst.room_by_id[p.room]
        students = {"SceCosC": 30, "ArcTec": 42, "TecCos": 40, "Geotec": 18}[inst.session_by_id[sid].course]
        assert room.capacity >= students


def test_solution_format():
    inst, cons = load_ctt(TOY)
    result = TimetableSolver(inst, cons, time_limit=10).solve()
    lines = to_ctt_solution(inst, result.assignment).splitlines()
    assert len(lines) == 16
    course, room, day, period = lines[0].split()
    assert course == "SceCosC" and room in {"A", "B", "C"} and 0 <= int(day) < 5 and 0 <= int(period) < 4


def test_bad_curriculum_count_rejected():
    with pytest.raises(CttFormatError):
        load_ctt(TOY.replace("Cur2 2 TecCos Geotec", "Cur2 3 TecCos Geotec"))
