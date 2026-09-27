"""Building the semester timetable from the course offering document.

The institute's week (from its published lecture and tutorial timetables):

* six lecture slots of 1 h 25 min: 08:30, 10:05, 11:40, 14:00, 15:35, 17:10;
* Mon/Tue/Wed are days A/B/C, and Thu/Fri/Sat repeat them: a course with
  three or more lecture hours meets twice a week in the same slot of a day
  and the day three later (Mon+Thu, Tue+Fri, Wed+Sat);
* tutorials on a one-hour grid (09:00, 10:30, 12:00, 14:00, 15:30, 17:00, 20:00);
* labs in blocks of up to three hours from 09:00 or 14:00;
* Wednesday and Saturday afternoons are kept free.

From each course's L-T-P (and, for labs, the area in its code: CS labs in the
computing labs, EC in the electronics labs, SC in the science lab):

* L >= 3: a lecture pair (same slot, day and day+3); L = 1-2 or "(H)": one
  lecture a week; a course bigger than the largest hall runs parallel
  sections in several halls;
* T > 0: one-hour tutorials, in parallel groups of at most 80;
* P > 0: a lab block of min(P, 3) hours, in parallel batches across the
  labs of its kind.

The solver works in two phases. Phase 1 (CP-SAT) chooses a time for every
session: no cohort, faculty member or room type is double-booked, per half
of the semester (an H1 and an H2 course may share a slot), and room demand
never exceeds supply at any capacity. Preferences, keeping electives of one
pool apart, avoiding the evening slot for first and second years and not
stacking a cohort's day are soft. Phase 2 gives each session actual rooms,
smallest that fits, keeping the previous rooms when repairing. An
independent check then re-verifies every hard rule on the result.

In the semester, a change (a faculty member away, a room closed, a new
preference) re-solves with every session's current time as the default:
moving a session costs more than any preference, so only what must move moves.
"""

from __future__ import annotations

import math
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from ortools.sat.python import cp_model
from pydantic import BaseModel, Field

from .offerings import Offering, OfferingDoc

# ---------------------------------------------------------------------------
# Calendar and rooms
# ---------------------------------------------------------------------------


def minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def clock(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


class Window(BaseModel):
    days: list[str]
    start: str
    end: str
    reason: str = ""


class SemesterCalendar(BaseModel):
    days: list[str] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    mirror: dict[str, str] = {"Mon": "Thu", "Tue": "Fri", "Wed": "Sat"}
    lecture_slots: list[tuple[str, str]] = [("08:30", "09:55"), ("10:05", "11:30"), ("11:40", "13:05"),
                                            ("14:00", "15:25"), ("15:35", "17:00"), ("17:10", "18:40")]
    tutorial_slots: list[tuple[str, str]] = [("09:00", "10:00"), ("10:30", "11:30"), ("12:00", "13:00"),
                                             ("14:00", "15:00"), ("15:30", "16:30"), ("17:00", "18:00"),
                                             ("20:00", "21:00")]
    lab_starts: list[str] = ["09:00", "14:00"]
    blocked: list[Window] = [Window(days=["Wed", "Sat"], start="14:00", end="18:40",
                                    reason="free afternoon (FSIS / free slot)")]
    club_hours: list[Window] = [Window(days=["Mon", "Tue", "Wed", "Thu", "Fri"], start="18:45", end="22:00"),
                                Window(days=["Wed", "Sat"], start="14:00", end="22:00")]
    weeks: int = 16  # H1 = weeks 1-8, H2 = weeks 9-16
    evening_slot: int = 6  # the 17:10 lecture slot

    def slot_of(self, start: int) -> int | None:
        for i, (a, _) in enumerate(self.lecture_slots, 1):
            if minutes(a) == start:
                return i
        return None


class Room(BaseModel):
    id: str
    capacity: int
    type: str = "lecture"  # lecture | computing | electronics | science | design


def default_rooms() -> list[Room]:
    """40 rooms named as in the institute's timetables."""
    rooms = [Room(id=f"SH{i}", capacity=c) for i, c in ((1, 300), (2, 250), (3, 250))]
    rooms += [Room(id=f"H{f}0{i}", capacity=c) for f, caps in ((1, (150, 120, 90, 70, 150)), (2, (150, 90, 90, 70, 120)),
                                                                (3, (120, 90, 70, 60)))
              for i, c in enumerate(caps, 1)]
    rooms += [Room(id=r, capacity=c) for r, c in (("B4-302", 60), ("B4-304", 60), ("B6-309", 60), ("D101", 50),
                                                  ("Digital Class Room", 80), ("N312", 40), ("N314", 40),
                                                  ("N328", 40), ("N329", 40), ("N332", 40), ("A3-302", 60),
                                                  ("A3-303", 60), ("B6-310", 50))]
    rooms += [Room(id=f"TL{i}", capacity=80, type="computing") for i in (1, 2, 3)]
    rooms += [Room(id=r, capacity=c, type="computing") for r, c in (("CL-1", 60), ("CL-2", 60))]
    rooms += [Room(id=r, capacity=c, type="electronics") for r, c in (("N114", 60), ("N125", 60), ("N117", 40))]
    rooms += [Room(id="A3-301", capacity=80, type="science"), Room(id="Design Studio", capacity=40, type="design")]
    return rooms


LAB_TYPE = {"CS": "computing", "EC": "electronics", "SC": "science", "PD": "design"}


def lab_type(course: Offering) -> str:
    """The kind of lab a practical needs, from the area in its code (and a few name hints)."""
    name = course.name.lower()
    if re.search(r"electronic|embedded|iot|vlsi|circuit|signal|microcontroller", name):
        return "electronics"
    if re.search(r"chemi|physics|biology|science lab", name):
        return "science"
    return LAB_TYPE.get(course.area, "computing")


def cohort_size(name: str) -> int:
    """A default enrolment per cohort; the office can override any of them."""
    n = name.upper()
    if "M.TECH" in n or "MTECH" in n:
        return 40
    if n.startswith("LE-"):
        return 20
    big = re.search(r"CSE|ECE", n) is not None
    return 180 if big and " I YEAR" in n else 150 if big else 40


# ---------------------------------------------------------------------------
# Sessions to place
# ---------------------------------------------------------------------------


@dataclass
class Option:
    intervals: list[tuple[str, int, int]]  # (day, start, end) in minutes
    slot: int | None = None  # lecture slot number, when on the lecture grid

    def label(self) -> str:
        return " + ".join(f"{d} {clock(a)}-{clock(b)}" for d, a, b in self.intervals)


@dataclass
class Component:
    id: str
    course: str
    kind: str  # lecture | tutorial | lab
    label: str  # "Lecture", "Tutorial 1 (group 2 of 3)", "Lab (batch 1 of 2)"
    rooms: list[int]  # minimum capacity of each room it needs at once
    room_type: str
    half: str  # full | H1 | H2
    cohorts: list[str]
    faculty: list[str]
    family: str  # parallel batches/groups of one course share a family: a cohort attends one of them
    options: list[Option] = field(default_factory=list)

    @property
    def halves(self) -> tuple[int, ...]:
        return (1,) if self.half == "H1" else (2,) if self.half == "H2" else (1, 2)


class Preference(BaseModel):
    id: str
    target: str  # "faculty" | "course" | "cohort"
    who: str  # faculty name, course code or cohort id
    mode: str = "avoid"  # avoid | prefer
    days: list[str] | None = None
    start: str | None = None  # a time window, e.g. before 10:00 -> start None, end "10:00"
    end: str | None = None
    hard: bool = False
    weight: int = 3
    text: str = ""  # what was asked, in words
    source: str = ""  # who asked


def faculty_key(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\(.*?\)|^(dr|prof)\.?\s+", "", name, flags=re.I)).strip().lower()


def components(doc: OfferingDoc, sizes: dict[str, int], rooms: list[Room], cal: SemesterCalendar) -> tuple[list[Component], list[str]]:
    notes = []
    comps: list[Component] = []
    lecture_rooms = sorted((r.capacity for r in rooms if r.type == "lecture"), reverse=True)
    biggest = lecture_rooms[0] if lecture_rooms else 100
    for c in doc.courses.values():
        if not c.scheduled:
            notes.append(f"{c.code} {c.name}: not timetabled ({c.note})")
            continue
        enrol = sum(sizes.get(h, 0) for h in c.cohorts)
        enrol = max(enrol, c.cap or (60 if c.pools else 0), 20)
        half = c.half if c.half in ("H1", "H2") else "full"
        fac = [faculty_key(f) for f in c.faculty if f and "coordinator" not in f.lower()] or \
              [faculty_key(f) for f in c.faculty]
        base = dict(course=c.code, half=half, cohorts=list(c.cohorts), faculty=fac)
        once = c.half == "H" or c.L in (1, 2)
        if c.L > 0 or (c.half == "H" and c.T > 0):
            # the fewest parallel sections whose size fits that many halls
            n = next((k for k in range(1, len(lecture_rooms) + 1) if lecture_rooms[k - 1] >= math.ceil(enrol / k)),
                     math.ceil(enrol / biggest))
            per = math.ceil(enrol / n)
            comps.append(Component(id=f"{c.code}/L", kind="lecture", label="Lecture" + (f" ({n} sections)" if n > 1 else ""),
                                   rooms=[per] * n, room_type="lecture", family=f"{c.code}/L",
                                   **{**base, "cohorts": base["cohorts"]}))
            comps[-1].options = _lecture_options(cal, once)
        if c.T > 0 and not (c.half == "H" and c.L == 0):
            # all groups of a tutorial meet in the same hour, one room each
            groups = math.ceil(enrol / 80)
            for t in range(min(c.T, 2)):
                comps.append(Component(id=f"{c.code}/T{t + 1}", kind="tutorial",
                                       label="Tutorial" + (f" {t + 1}" if c.T > 1 else "") +
                                             (f" ({groups} groups)" if groups > 1 else ""),
                                       rooms=[math.ceil(enrol / groups)] * groups, room_type="lecture",
                                       family=f"{c.code}/T{t + 1}", **base))
                comps[-1].options = _tutorial_options(cal)
        if c.P > 0:
            kind = lab_type(c)
            labs = sorted((r.capacity for r in rooms if r.type == kind), reverse=True)
            if not labs:
                notes.append(f"{c.code}: needs a {kind} lab and there is none")
                continue
            per_batch = sum(labs)
            hours = min(c.P, 3)
            batches = _lab_batches(c.cohorts, sizes, enrol, per_batch)
            for b, (members, size) in enumerate(batches):
                need, left = [], size
                for cap in labs:
                    if left <= 0:
                        break
                    need.append(min(cap, left))
                    left -= cap
                comps.append(Component(id=f"{c.code}/P.{b + 1}", kind="lab",
                                       label=f"Lab ({hours} h)" + (f" (batch {b + 1} of {len(batches)})" if len(batches) > 1 else ""),
                                       rooms=need, room_type=kind, family=f"{c.code}/P",
                                       **{**base, "faculty": [], "cohorts": members}))  # labs are run by TAs and staff
                comps[-1].options = _lab_options(cal, hours)
    for comp in comps:
        comp.options = [o for o in comp.options if not _blocked(cal, o)]
    return comps, notes


def _lab_batches(cohorts: list[str], sizes: dict[str, int], enrol: int, capacity: int) -> list[tuple[list[str], int]]:
    """Lab batches made of whole programmes where possible, so each programme is
    busy only during its own batch; a programme too big for one batch is split
    (and is then busy during each of its batches)."""
    if not cohorts:
        n = math.ceil(enrol / capacity)
        return [([], math.ceil(enrol / n))] * n
    pieces: list[tuple[str, int]] = []
    for h in sorted(cohorts, key=lambda h: -sizes.get(h, 0)):
        size = max(1, sizes.get(h, 0))
        n = math.ceil(size / capacity)
        pieces += [(h, math.ceil(size / n))] * n
    batches: list[list] = []  # [members, size]
    for h, size in pieces:  # first fit, largest first
        slot = next((b for b in batches if b[1] + size <= capacity and h not in b[0]), None)
        if slot is None:
            batches.append([[h], size])
        else:
            slot[0].append(h)
            slot[1] += size
    return [(members, size) for members, size in batches]


def _lecture_options(cal: SemesterCalendar, once: bool) -> list[Option]:
    out = []
    for s, (a, b) in enumerate(cal.lecture_slots, 1):
        if once:
            out += [Option([(d, minutes(a), minutes(b))], s) for d in cal.days]
        else:
            out += [Option([(d, minutes(a), minutes(b)), (m, minutes(a), minutes(b))], s) for d, m in cal.mirror.items()]
    return out


def _tutorial_options(cal: SemesterCalendar) -> list[Option]:
    return [Option([(d, minutes(a), minutes(b))]) for d in cal.days for a, b in cal.tutorial_slots]


def _lab_options(cal: SemesterCalendar, hours: int) -> list[Option]:
    return [Option([(d, minutes(s), minutes(s) + 60 * hours)]) for d in cal.days for s in cal.lab_starts]


def _blocked(cal: SemesterCalendar, o: Option) -> bool:
    return any(d in w.days and a < minutes(w.end) and minutes(w.start) < b for d, a, b in o.intervals for w in cal.blocked)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


class Meeting(BaseModel):
    component: str
    course: str
    name: str
    kind: str
    label: str
    day: str
    start: str
    end: str
    slot: int | None = None
    rooms: list[str]
    faculty: list[str]
    cohorts: list[str]
    half: str


class BuildReport(BaseModel):
    status: str
    seconds: float
    components: int
    meetings: int
    hard_violations: list[str] = Field(default_factory=list)
    preferences: list[dict] = Field(default_factory=list)  # {id, text, met}
    pool_clashes: int = 0
    evening_sessions: int = 0
    moved: int = 0
    notes: list[str] = Field(default_factory=list)
    room_use: dict[str, float] = Field(default_factory=dict)


class Timetable(BaseModel):
    meetings: list[Meeting]
    report: BuildReport
    choice: dict[str, int] = Field(default_factory=dict)  # component -> option index
    rooms: dict[str, list[str]] = Field(default_factory=dict)  # component -> rooms


# ---------------------------------------------------------------------------
# The solver
# ---------------------------------------------------------------------------


def _covers(o: Option, day: str, t: int) -> bool:
    return any(d == day and a <= t < b for d, a, b in o.intervals)


def _pref_violated(p: Preference, o: Option) -> bool:
    lo = minutes(p.start) if p.start else 0
    hi = minutes(p.end) if p.end else 24 * 60
    inside = [(p.days is None or d in p.days) and a < hi and lo < b for d, a, b in o.intervals]
    return any(inside) if p.mode == "avoid" else not all(inside)


def _applies(p: Preference, c: Component) -> bool:
    if p.target == "course":
        return c.course.lower() == p.who.lower()
    if p.target == "cohort":
        return p.who in c.cohorts
    return faculty_key(p.who) in c.faculty


class SemesterSolver:
    """Two-phase CP-SAT build or repair of the semester timetable."""

    def __init__(self, doc: OfferingDoc, *, rooms: list[Room] | None = None, sizes: dict[str, int] | None = None,
                 calendar: SemesterCalendar | None = None, preferences: list[Preference] | None = None,
                 room_closures: list[tuple[str, Window]] | None = None, time_limit: float = 60.0,
                 workers: int = 8) -> None:
        self.doc = doc
        self.cal = calendar or SemesterCalendar()
        self.rooms = rooms or default_rooms()
        self.sizes = {c.id: (sizes or {}).get(c.id, c.size or cohort_size(c.name)) for c in doc.cohorts}
        self.preferences = preferences or []
        self.closures = room_closures or []
        self.time_limit = time_limit
        self.workers = workers
        self.comps, self.notes = components(doc, self.sizes, self.rooms, self.cal)
        self.pool_of = defaultdict(set)
        for p in doc.pools:
            for code in p.courses:
                self.pool_of[code].add(p.id)
        self.early_years = {c.id for c in doc.cohorts if re.search(r"\bI+ year\b", c.name) and
                            re.search(r"\b(I|II) year", c.name) and "B.TECH" in c.name.upper()}

    # -- phase 1: times ---------------------------------------------------------------

    def solve(self, baseline: Timetable | None = None, *, without: frozenset[str] = frozenset()) -> Timetable:
        """``without`` drops families of hard constraints ("cohort", "faculty", "rooms"),
        to find out which one makes a build infeasible."""
        t0 = time.perf_counter()
        comps = self.comps
        m = cp_model.CpModel()
        y = {c.id: [m.new_bool_var(f"y[{c.id},{k}]") for k in range(len(c.options))] for c in comps}
        for c in comps:
            m.add_exactly_one(y[c.id])
        hard_prefs = [p for p in self.preferences if p.hard]
        for c in comps:
            for p in hard_prefs:
                if _applies(p, c):
                    for k, o in enumerate(c.options):
                        if _pref_violated(p, o):
                            m.add(y[c.id][k] == 0)

        points = {d: sorted({a for c in comps for o in c.options for dd, a, _ in o.intervals if dd == d}) for d in self.cal.days}

        def covering(c: Component, day: str, t: int) -> list:
            return [y[c.id][k] for k, o in enumerate(c.options) if _covers(o, day, t)]

        # families: parallel batches/groups count once for their cohorts
        fam_vars: dict[tuple, cp_model.IntVar] = {}

        def fam_var(fam: str, members: list[Component], day: str, t: int, half: int):
            # the members differ by half (H1/H2) and by programme (lab batches): key on them
            key = (fam, day, t, half, tuple(sorted(c.id for c in members)))
            if key not in fam_vars:
                vs = [v for c in members for v in covering(c, day, t)]
                if not vs:
                    fam_vars[key] = None
                elif len(members) == 1:
                    fam_vars[key] = sum(vs)
                else:
                    z = m.new_bool_var(f"z[{fam},{day},{t}]")
                    for v in vs:
                        m.add_implication(v, z)
                    fam_vars[key] = z
            return fam_vars[key]

        by_cohort = defaultdict(lambda: defaultdict(list))
        by_fac = defaultdict(list)
        for c in comps:
            for h in c.cohorts:
                by_cohort[h][c.family].append(c)
            for f in c.faculty:
                by_fac[f].append(c)
        by_type = defaultdict(list)
        for r in self.rooms:
            by_type[r.type].append(r.capacity)

        for d in self.cal.days:
            for t in points[d]:
                for half in (1, 2):
                    for h, fams in ({} if "cohort" in without else by_cohort).items():
                        terms = [fam_var(fam, [c for c in mem if half in c.halves], d, t, half) for fam, mem in fams.items()]
                        terms = [x for x in terms if x is not None]
                        if len(terms) > 1:
                            m.add(sum(terms) <= 1)
                    for f, cs in ({} if "faculty" in without else by_fac).items():
                        vs = [v for c in cs if half in c.halves for v in covering(c, d, t)]
                        if len(vs) > 1:
                            m.add(sum(vs) <= 1)
                    for rtype, caps in ({} if "rooms" in without else by_type).items():
                        # rooms needed with capacity >= k never exceed rooms available with capacity >= k
                        demand = [(c, k) for c in comps if c.room_type == rtype
                                  and half in c.halves for k, o in enumerate(c.options) if _covers(o, d, t)]
                        if not demand:
                            continue
                        closed_ids = {r_id for r_id, cl in self.closures
                                      if d in cl.days and minutes(cl.start) <= t < minutes(cl.end)}
                        avail = [r.capacity for r in self.rooms if r.type == rtype and r.id not in closed_ids]
                        for kcap in sorted({need for c, _ in demand for need in c.rooms}):
                            supply = sum(1 for cap in avail if cap >= kcap)
                            terms = [y[c.id][k] * sum(1 for need in c.rooms if need >= kcap) for c, k in demand
                                     if any(need >= kcap for need in c.rooms)]
                            if terms:
                                m.add(sum(terms) <= supply)

        # soft goals
        cost = []
        for c in comps:
            for p in self.preferences:
                if p.hard or not _applies(p, c):
                    continue
                for k, o in enumerate(c.options):
                    if _pref_violated(p, o):
                        cost.append(p.weight * 10 * y[c.id][k])
            if self.early_years & set(c.cohorts) and c.kind == "lecture":
                cost += [4 * y[c.id][k] for k, o in enumerate(c.options) if o.slot == self.cal.evening_slot]
            if c.kind == "lecture":
                cost += [1 * y[c.id][k] for k, o in enumerate(c.options) if o.slot == self.cal.evening_slot]
            late = [k for k, o in enumerate(c.options) if c.kind == "tutorial" and o.intervals[0][1] >= minutes("20:00")]
            cost += [(4 if self.early_years & set(c.cohorts) else 1) * y[c.id][k] for k in late]
        # electives of one pool: keep apart (students take several)
        lec = {c.course: c for c in comps if c.kind == "lecture"}
        for a, b in combinations(sorted(lec), 2):
            if not (self.pool_of[a] & self.pool_of[b]):
                continue
            ca, cb = lec[a], lec[b]
            if not set(ca.halves) & set(cb.halves):
                continue
            for ka, oa in enumerate(ca.options):
                for kb, ob in enumerate(cb.options):
                    if oa.intervals == ob.intervals:
                        clash = m.new_bool_var("")
                        m.add_bool_and([y[a + "/L"][ka], y[b + "/L"][kb]]).only_enforce_if(clash)
                        m.add_bool_or([y[a + "/L"][ka].Not(), y[b + "/L"][kb].Not(), clash])
                        cost.append(6 * clash)
        # a cohort's day should not stack more than two lecture meetings
        for h, fams in by_cohort.items():
            for d in self.cal.days:
                day_terms = [y[c.id][k] for mem in fams.values() for c in mem if c.kind == "lecture"
                             for k, o in enumerate(c.options) if any(dd == d for dd, _, _ in o.intervals)]
                if len(day_terms) > 2:
                    over = m.new_int_var(0, len(day_terms), "")
                    m.add(over >= sum(day_terms) - 2)
                    cost.append(3 * over)
        # repair: every move costs more than any preference
        if baseline is not None:
            for c in comps:
                k0 = baseline.choice.get(c.id)
                if k0 is not None and k0 < len(c.options):
                    cost.append(200 * (1 - y[c.id][k0]))
                    m.add_hint(y[c.id][k0], 1)
        m.minimize(sum(cost))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit
        solver.parameters.num_workers = self.workers
        status = solver.solve(m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            report = BuildReport(status="infeasible" if status == cp_model.INFEASIBLE else "no solution in time",
                                 seconds=time.perf_counter() - t0, components=len(comps), meetings=0, notes=self.notes)
            return Timetable(meetings=[], report=report)
        choice = {c.id: next(k for k, v in enumerate(y[c.id]) if solver.value(v)) for c in comps}
        rooms = self._rooms(choice, baseline)
        tt = self._timetable(choice, rooms)
        tt.report.status = "optimal" if status == cp_model.OPTIMAL else "feasible"
        tt.report.seconds = round(time.perf_counter() - t0, 1)
        if baseline is not None:
            tt.report.moved = sum(1 for c in comps if baseline.choice.get(c.id) != choice[c.id])
        return tt

    # -- phase 2: rooms ------------------------------------------------------------------

    def _rooms(self, choice: dict[str, int], baseline: Timetable | None) -> dict[str, list[str]]:
        m = cp_model.CpModel()
        a: dict[str, dict[str, cp_model.IntVar]] = {}
        cost = []
        for c in self.comps:
            o = c.options[choice[c.id]]
            closed = {r_id for r_id, cl in self.closures for d, s, e in o.intervals
                      if d in cl.days and s < minutes(cl.end) and minutes(cl.start) < e}
            smallest = min(c.rooms)
            cands = [r for r in self.rooms if r.type == c.room_type and r.capacity >= smallest and r.id not in closed]
            a[c.id] = {r.id: m.new_bool_var(f"a[{c.id},{r.id}]") for r in cands}
            m.add(sum(a[c.id].values()) == len(c.rooms))
            # the biggest needs must each get a room big enough
            for need in sorted(set(c.rooms)):
                m.add(sum(v for r_id, v in a[c.id].items() if self._cap(r_id) >= need) >= sum(1 for x in c.rooms if x >= need))
            prev = set(baseline.rooms.get(c.id, [])) if baseline else set()
            for r_id, v in a[c.id].items():
                cost.append((self._cap(r_id) - smallest) * v)  # waste
                if r_id not in prev and prev:
                    cost.append(500 * v)
        for d in self.cal.days:
            pts = sorted({s for c in self.comps for dd, s, _ in c.options[choice[c.id]].intervals if dd == d})
            for t in pts:
                for half in (1, 2):
                    live = [c for c in self.comps if half in c.halves and _covers(c.options[choice[c.id]], d, t)]
                    by_room = defaultdict(list)
                    for c in live:
                        for r_id, v in a[c.id].items():
                            by_room[r_id].append(v)
                    for vs in by_room.values():
                        if len(vs) > 1:
                            m.add(sum(vs) <= 1)
        m.minimize(sum(cost))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(10.0, self.time_limit / 2)
        solver.parameters.num_workers = self.workers
        status = solver.solve(m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return {c.id: [] for c in self.comps}
        return {c.id: sorted(r for r, v in a[c.id].items() if solver.value(v)) for c in self.comps}

    def _cap(self, room_id: str) -> int:
        return next(r.capacity for r in self.rooms if r.id == room_id)

    # -- assembling and checking --------------------------------------------------------

    def _timetable(self, choice: dict[str, int], rooms: dict[str, list[str]]) -> Timetable:
        meetings = []
        for c in self.comps:
            o = c.options[choice[c.id]]
            for d, a, b in o.intervals:
                meetings.append(Meeting(component=c.id, course=c.course, name=self.doc.courses[c.course].name,
                                        kind=c.kind, label=c.label, day=d, start=clock(a), end=clock(b), slot=o.slot,
                                        rooms=rooms.get(c.id, []), faculty=c.faculty, cohorts=c.cohorts, half=c.half))
        report = BuildReport(status="", seconds=0, components=len(self.comps), meetings=len(meetings), notes=self.notes)
        report.hard_violations = verify(meetings, self.rooms, self.sizes, self.cal, self.comps, self.closures)
        for p in self.preferences:
            hits = [c for c in self.comps if _applies(p, c)]
            met = all(not _pref_violated(p, c.options[choice[c.id]]) for c in hits)
            report.preferences.append({"id": p.id, "text": p.text or p.who, "met": met, "hard": p.hard,
                                       "sessions": len(hits)})
        lec = {c.course: c for c in self.comps if c.kind == "lecture"}
        report.pool_clashes = sum(
            1 for a, b in combinations(sorted(lec), 2) if self.pool_of[a] & self.pool_of[b]
            and set(lec[a].halves) & set(lec[b].halves)
            and lec[a].options[choice[lec[a].id]].intervals == lec[b].options[choice[lec[b].id]].intervals)
        report.evening_sessions = sum(1 for mt in meetings if mt.slot == self.cal.evening_slot)
        busy = defaultdict(int)
        for mt in meetings:
            for r in mt.rooms:
                busy[r] += minutes(mt.end) - minutes(mt.start)
        week = sum(minutes(b) - minutes(a) for a, b in self.cal.lecture_slots) * len(self.cal.days)
        report.room_use = {r.id: round(busy[r.id] / week, 3) for r in self.rooms}
        return Timetable(meetings=meetings, report=report, choice=choice, rooms=rooms)


def verify(meetings: list[Meeting], rooms: list[Room], sizes: dict[str, int], cal: SemesterCalendar,
           comps: list[Component] | None = None, closures: list[tuple[str, Window]] | None = None) -> list[str]:
    """Independent check of the hard rules on a finished timetable."""
    problems = []
    room = {r.id: r for r in rooms}
    comp = {c.id: c for c in comps or []}
    fam = {c.id: c.family for c in comps or []}
    halves = {"H1": (1,), "H2": (2,), "full": (1, 2)}

    def overlap(x: Meeting, z: Meeting) -> bool:
        return (x.day == z.day and minutes(x.start) < minutes(z.end) and minutes(z.start) < minutes(x.end)
                and bool(set(halves[x.half]) & set(halves[z.half])))

    by_day = defaultdict(list)
    for mt in meetings:
        by_day[mt.day].append(mt)
        for w in cal.blocked:
            if mt.day in w.days and minutes(mt.start) < minutes(w.end) and minutes(w.start) < minutes(mt.end):
                problems.append(f"{mt.course} {mt.label} on {mt.day} {mt.start} is in a blocked window ({w.reason})")
        for r_id in mt.rooms:
            if mt.component in comp and room[r_id].type != comp[mt.component].room_type:
                problems.append(f"{mt.course} {mt.label}: {r_id} is a {room[r_id].type} room, needs {comp[mt.component].room_type}")
            for r2, w in closures or []:
                if r2 == r_id and mt.day in w.days and minutes(mt.start) < minutes(w.end) and minutes(w.start) < minutes(mt.end):
                    problems.append(f"{mt.course} {mt.label} uses {r_id}, which is closed then")
        if mt.component in comp and len(mt.rooms) != len(comp[mt.component].rooms):
            problems.append(f"{mt.course} {mt.label}: {len(mt.rooms)} rooms for {len(comp[mt.component].rooms)} needed")
        if mt.component in comp:
            caps = sorted((room[r].capacity for r in mt.rooms), reverse=True)
            needs = sorted(comp[mt.component].rooms, reverse=True)
            if any(cap < need for cap, need in zip(caps, needs)):
                problems.append(f"{mt.course} {mt.label}: rooms {mt.rooms} too small for {needs}")
    for day, ms in by_day.items():
        for x, z in combinations(ms, 2):
            if x.component == z.component or not overlap(x, z):
                continue
            if set(x.rooms) & set(z.rooms):
                problems.append(f"room clash {day} {x.start}: {x.course} and {z.course} in {set(x.rooms) & set(z.rooms)}")
            if set(x.faculty) & set(z.faculty) and x.kind != "lab" and z.kind != "lab":
                problems.append(f"faculty clash {day} {x.start}: {x.course} and {z.course} ({', '.join(set(x.faculty) & set(z.faculty))})")
            same_family = fam.get(x.component) == fam.get(z.component) and fam.get(x.component) is not None
            if set(x.cohorts) & set(z.cohorts) and not same_family:
                problems.append(f"cohort clash {day} {x.start}: {x.course} and {z.course}")
    return problems
