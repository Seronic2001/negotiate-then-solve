"""The semester timetable as a service: offerings, preferences, builds,
versions, in-semester changes and club bookings, saved to disk.

Builds and repairs run in a background thread (a full build takes about a
minute); the web app polls ``status``. Nothing a build produces is live until
the timetable office publishes that version.
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .clubs import ClubDecision, ClubDesk, ClubRequest
from .offerings import OfferingDoc, parse_offerings
from .requests import parse
from .solver import (
    Preference,
    Room,
    SemesterCalendar,
    SemesterSolver,
    Timetable,
    Window,
    cohort_size,
    components,
    default_rooms,
)


class Closure(BaseModel):
    room: str
    window: Window
    text: str = ""


class Version(BaseModel):
    version: int
    created: str
    kind: str  # build | change
    note: str = ""
    published: bool = False
    based_on: int | None = None
    diff: list[dict] = Field(default_factory=list)
    timetable: Timetable


class SemesterState(BaseModel):
    doc: OfferingDoc | None = None
    sizes: dict[str, int] = Field(default_factory=dict)
    preferences: list[Preference] = Field(default_factory=list)
    closures: list[Closure] = Field(default_factory=list)
    versions: list[Version] = Field(default_factory=list)
    bookings: list[ClubDecision] = Field(default_factory=list)
    semester_start: str = "2026-07-27"


class SemesterPlanner:
    def __init__(self, folder: Path, sample: Path | None = None, time_limit: float = 60.0) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "state.json"
        self.sample = sample
        self.time_limit = time_limit
        self.calendar = SemesterCalendar()
        self.rooms: list[Room] = default_rooms()
        self.state = SemesterState.model_validate_json(self.path.read_text(encoding="utf-8")) \
            if self.path.exists() else SemesterState()
        self.lock = threading.Lock()
        self.job: dict = {"running": False}

    def save(self) -> None:
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(self.state.model_dump_json(), encoding="utf-8")
            tmp.replace(self.path)

    # -- offerings ---------------------------------------------------------------------

    def load_offerings(self, path: Path) -> OfferingDoc:
        doc = parse_offerings(path)
        if not doc.courses:
            raise ValueError("no courses found: expected rows with a course code and L-T-P-C credits")
        self.state.doc = doc
        self.state.sizes = {c.id: self.state.sizes.get(c.id, cohort_size(c.name)) for c in doc.cohorts}
        self.save()
        return doc

    def set_sizes(self, sizes: dict[str, int]) -> None:
        for k, v in sizes.items():
            if k in self.state.sizes and 0 < int(v) < 2000:
                self.state.sizes[k] = int(v)
        self.save()

    def needs(self) -> dict[str, list[dict]]:
        """What each course needs, as the solver will place it (for review before building)."""
        if not self.state.doc:
            return {}
        comps, _ = components(self.state.doc, self.state.sizes, self.rooms, self.calendar)
        out: dict[str, list[dict]] = {}
        for c in comps:
            out.setdefault(c.course, []).append({"kind": c.kind, "label": c.label, "rooms": c.rooms,
                                                 "room_type": c.room_type, "options": len(c.options),
                                                 "pair": len(c.options[0].intervals) > 1 if c.options else False})
        return out

    # -- preferences and closures --------------------------------------------------------

    def add(self, text: str, source: str, preview: bool = False) -> dict:
        if not self.state.doc:
            raise ValueError("load the course offerings first")
        parsed = parse(text, self.state.doc, self.rooms, source)
        if parsed.error:
            return {"ok": False, "error": parsed.error}
        if not preview:
            self.state.preferences += parsed.preferences
            self.state.closures += [Closure(room=r, window=w, text=text) for r, w in parsed.closures]
            self.save()
        return {"ok": True, "summary": parsed.summary, "preferences": [p.model_dump() for p in parsed.preferences],
                "closures": [{"room": r, **w.model_dump()} for r, w in parsed.closures]}

    def remove_preference(self, pid: str) -> None:
        self.state.preferences = [p for p in self.state.preferences if p.id != pid]
        self.save()

    # -- builds ----------------------------------------------------------------------------

    def published(self) -> Version | None:
        return next((v for v in reversed(self.state.versions) if v.published), None)

    def _solver(self) -> SemesterSolver:
        return SemesterSolver(self.state.doc, rooms=self.rooms, sizes=self.state.sizes, calendar=self.calendar,
                              preferences=self.state.preferences,
                              room_closures=[(c.room, c.window) for c in self.state.closures],
                              time_limit=self.time_limit)

    def start(self, kind: str, note: str = "") -> None:
        if not self.state.doc:
            raise ValueError("load the course offerings first")
        if self.job.get("running"):
            raise RuntimeError("a build is already running")
        base = self.published() if kind == "change" else None
        if kind == "change" and base is None:
            raise ValueError("publish a timetable before proposing changes to it")
        self.job = {"running": True, "kind": kind, "note": note, "started": time.time(), "error": None,
                    "version": None}
        threading.Thread(target=self._run, args=(kind, note, base), daemon=True).start()

    def _run(self, kind: str, note: str, base: Version | None) -> None:
        try:
            tt = self._solver().solve(base.timetable if base else None)
            if not tt.meetings:
                self.job.update(running=False, error=f"no timetable: {tt.report.status}", report=tt.report.model_dump())
                return
            v = Version(version=len(self.state.versions) + 1, created=datetime.now().isoformat(timespec="seconds"),
                        kind=kind, note=note, based_on=base.version if base else None, timetable=tt,
                        diff=diff(base.timetable, tt) if base else [])
            self.state.versions.append(v)
            self.save()
            self.job.update(running=False, version=v.version)
        except Exception as e:  # noqa: BLE001 - surfaced in the UI
            self.job.update(running=False, error=f"{type(e).__name__}: {e}")

    def status(self) -> dict:
        j = dict(self.job)
        if j.get("running"):
            j["elapsed"] = round(time.time() - j["started"], 1)
        return j

    def publish(self, version: int) -> Version:
        v = next((x for x in self.state.versions if x.version == version), None)
        if v is None:
            raise KeyError(version)
        if v.timetable.report.hard_violations:
            raise ValueError("this version breaks hard rules and cannot be published")
        for x in self.state.versions:
            x.published = x.version == version
        self.save()
        return v

    # -- clubs -------------------------------------------------------------------------------

    def desk(self) -> ClubDesk:
        return ClubDesk(self.calendar, self.rooms, date.fromisoformat(self.state.semester_start))

    def club(self, req: ClubRequest, submit: bool, rules: list[dict], today: date | None = None) -> ClubDecision:
        v = self.published()
        if v is None:
            raise ValueError("there is no published semester timetable yet")
        d = self.desk().check(req, v.timetable.meetings, self.state.bookings, today, rules)
        if submit:
            self.state.bookings.append(d)
            self.save()
        return d

    def decide(self, booking: str, approve: bool) -> ClubDecision:
        d = next(b for b in self.state.bookings if b.id == booking)
        if d.status != "needs_approval":
            raise ValueError("only requests waiting for the office can be decided")
        d.status = "booked" if approve else "rejected"
        self.save()
        return d


def diff(before: Timetable, after: Timetable) -> list[dict]:
    """Sessions whose time or rooms changed between two versions."""
    def where(tt: Timetable) -> dict[str, tuple[str, list[str]]]:
        out: dict[str, tuple[str, list[str]]] = {}
        for m in tt.meetings:
            t, rooms = out.get(m.component, ("", m.rooms))
            out[m.component] = ((t + " + " if t else "") + f"{m.day} {m.start}", rooms)
        return out

    a, b = where(before), where(after)
    label = {m.component: (m.course, m.name, m.label) for m in after.meetings}
    rows = []
    for comp in sorted(set(a) | set(b)):
        if a.get(comp) != b.get(comp):
            course, name, lab = label.get(comp, (comp, "", ""))
            rows.append({"component": comp, "course": course, "name": name, "label": lab,
                         "before": f"{a[comp][0]} · {', '.join(a[comp][1])}" if comp in a else "—",
                         "after": f"{b[comp][0]} · {', '.join(b[comp][1])}" if comp in b else "—"})
    return rows
