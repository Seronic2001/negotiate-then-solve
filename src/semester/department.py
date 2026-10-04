"""A department from a course offering document: the people, sections, rooms and
weekly sessions a world of the web app runs on.

    doc = parse_offerings(Path("course-offering/CampusCourseOfferings-M26.pdf"))
    instance = instance_from_offerings(doc, sizes)

* **People.** Every faculty name in the document becomes a teacher
  (``F-101`` ...); a name written ``Dr. X (Visiting)`` becomes visiting
  faculty. The teacher with the most courses in each area (CS, EC, ...) is that
  department's head; the others report to them. A Dean heads the heads.
* **Sections.** Each programme (cohort) becomes a section of students with a
  class representative; elective pools with no programme are left out of the
  weekly timetable.
* **Sessions.** L lectures and T tutorials of an hour each, and the P practical
  hours as one lab block (two blocks when P > 3), for every programme that
  takes the course together: a course two programmes share is one combined
  lecture in a big room.
* **Rooms.** Enough lecture rooms for the week's lecture hours, sized so the
  largest combined class fits (halls), and labs of each kind the practicals need.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from core.instance import (
    Calendar,
    Faculty,
    Group,
    Instance,
    Room,
    RoomType,
    Session,
    SessionKind,
)
from core.schemas import Role

from .offerings import OfferingDoc
from .solver import cohort_size, lab_type

VISITING = re.compile(r"\((?:visiting|guest)\)", re.IGNORECASE)
SIZE_NOTE = re.compile(r"\s*\(\d{1,3} students\)", re.IGNORECASE)
AREA_NAME = {"CS": "CSE", "EC": "ECE", "MA": "Mathematics", "SC": "Sciences", "HS": "Humanities"}
# semester lab blocks a week: 09:00 and 14:00 on six days, less the free Wednesday and Saturday afternoons
SEMESTER_LAB_BLOCKS = 10
LAB_EQUIPMENT = {"computing": ["gpu"], "electronics": ["electronics"], "science": ["science"], "design": ["design"]}


def _clean(name: str) -> str:
    return re.sub(r"\s+", " ", VISITING.sub("", name)).strip()


def instance_from_offerings(doc: OfferingDoc, sizes: dict[str, int] | None = None, name: str | None = None,
                            calendar: Calendar | None = None) -> Instance:
    sizes = sizes or {}
    cohorts = [c for c in doc.cohorts if c.courses]
    group_id = {c.id: f"G-{i + 1:02d}" for i, c in enumerate(cohorts)}
    groups = [Group(id=group_id[c.id], name=SIZE_NOTE.sub("", c.name).strip(),
                    size=sizes.get(c.id) or c.size or cohort_size(c.name)) for c in cohorts]
    size_of = {g.id: g.size for g in groups}

    courses = [c for c in doc.courses.values() if c.scheduled and c.faculty and any(x in group_id for x in c.cohorts)]
    # people: first appearance order, so ids are stable for the same document
    names: dict[str, str] = {}
    visiting: set[str] = set()
    per_area: dict[str, Counter] = defaultdict(Counter)
    for c in courses:
        for raw in c.faculty:
            n = _clean(raw)
            if not n or "coordinator" in n.lower():
                continue
            if n not in names:
                names[n] = f"F-{101 + len(names)}"
            if VISITING.search(raw):
                visiting.add(n)
            per_area[c.area][n] += 1
    heads = {}
    for area, counts in per_area.items():
        head = next((n for n, _ in counts.most_common() if n not in visiting and n not in heads.values()), None)
        if head:
            heads[area] = head
    area_of = {n: max(per_area, key=lambda a, n=n: per_area[a][n]) for n in names}
    dean_id = "F-100"
    faculty = [Faculty(id=dean_id, name="Dr. Dean (Academics)", department="Academics", role=Role.DEAN)]
    for n, fid in names.items():
        area = area_of[n]
        head = heads.get(area)
        role = Role.HOD if n in heads.values() else Role.GUEST_FACULTY if n in visiting else Role.FACULTY
        faculty.append(Faculty(id=fid, name=n, department=AREA_NAME.get(area, area), role=role,
                               reports_to=dean_id if role == Role.HOD else names.get(head) if head else dean_id))

    sessions: list[Session] = []
    titles: dict[str, str] = {}
    lab_kinds: Counter = Counter()
    lab_blocks: Counter = Counter()  # lab meetings per kind in the semester plan (one block per section)
    for c in courses:
        gs = [group_id[x] for x in c.cohorts if x in group_id]
        teachers = [names[_clean(f)] for f in c.faculty if _clean(f) in names] or [next(iter(names.values()))]
        titles[c.code] = c.name
        for k in range(c.L):
            sessions.append(Session(id=f"{c.code}-L{k + 1}", course=c.code, kind=SessionKind.LECTURE,
                                    faculty=teachers[k % len(teachers)], groups=gs))
        for k in range(c.T):
            sessions.append(Session(id=f"{c.code}-T{k + 1}", course=c.code, kind=SessionKind.TUTORIAL,
                                    faculty=teachers[-1], groups=gs))
        if c.P:
            kind = lab_type(c)
            blocks = [c.P] if c.P <= 3 else [math.ceil(c.P / 2), c.P // 2]
            for b, hours in enumerate(blocks):
                for g in gs:  # a lab runs per section: labs are not shared like lectures
                    sessions.append(Session(id=f"{c.code}-P{b + 1}-{g}", course=c.code, kind=SessionKind.PRACTICAL,
                                            faculty=teachers[-1], groups=[g], duration=hours, room_type=RoomType.LAB,
                                            equipment=LAB_EQUIPMENT.get(kind, [])))
                    lab_kinds[kind] += hours
                    if b == 0:
                        lab_blocks[kind] += 1

    rooms = _rooms(sessions, size_of, lab_kinds, lab_blocks, calendar or Calendar())
    return Instance(name=name or doc.source, calendar=calendar or Calendar(), rooms=rooms, faculty=faculty,
                    groups=groups, sessions=sessions, course_titles=titles)


def _rooms(sessions: list[Session], size_of: dict[str, int], lab_kinds: Counter, lab_blocks: Counter,
           cal: Calendar) -> list[Room]:
    """Lecture rooms for twice the week's lecture hours, the biggest classes in halls; labs per kind,
    enough for both the weekly timetable and the semester plan."""
    usable = len(cal.days) * (cal.slots_per_day - (1 if cal.lunch_slot is not None else 0))
    lectures = [s for s in sessions if s.room_type == RoomType.LECTURE]
    need = [sum(size_of[g] for g in s.groups) for s in lectures]
    n_rooms = max(4, math.ceil(len(lectures) * 2.0 / usable))  # half the room-hours spare: moves have room to land
    halls = sorted({n for n in need if n > 120}, reverse=True)
    rooms: list[Room] = []
    for i, cap in enumerate(halls[:3]):  # one hall per distinct big class, at most three
        cap = int(math.ceil(cap / 20) * 20)
        rooms.append(Room(id=f"H-{i + 1}", name=f"Hall {chr(65 + i)}", capacity=cap, type=RoomType.LECTURE))
    biggest_section = max((n for n in need if n <= 120), default=60)
    for i in range(max(n_rooms - len(rooms), 2)):
        cap = 120 if i < 2 else max(60, int(math.ceil(biggest_section / 10) * 10)) if i % 3 else 80
        rooms.append(Room(id=f"R-{101 + i}", name=f"Room {101 + i}", capacity=cap, type=RoomType.LECTURE))
    n = 1
    for kind, hours in sorted(lab_kinds.items()):
        # the semester plan has SEMESTER_LAB_BLOCKS three-hour lab blocks a week per lab; keep a fifth spare
        semester = math.ceil(lab_blocks[kind] * 1.25 / SEMESTER_LAB_BLOCKS)
        for _ in range(max(1, math.ceil(hours * 1.4 / usable), semester)):
            rooms.append(Room(id=f"L-{n}", name=f"Lab {n}", capacity=80, type=RoomType.LAB,
                              equipment=LAB_EQUIPMENT.get(kind, [])))
            n += 1
    # the one lab with routers: requests for routers have to share it (a planted contention)
    labs = [r for r in rooms if r.type == RoomType.LAB and "gpu" in r.equipment]
    if labs:
        labs[0].equipment = [*labs[0].equipment, "routers"]
    return rooms
