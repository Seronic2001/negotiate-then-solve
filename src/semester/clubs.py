"""Club activities in the evenings and free afternoons, checked automatically.

A club (through a student) asks for a room at a date and time for so many
people, and names the programmes its members come from. Every check is
against the published semester timetable and the bookings already made:

1. inside club hours (weekday evenings, the free Wednesday and Saturday afternoons);
2. enough notice (two days; the auditorium five working days, as the booking rules say);
3. the members' programmes have no class, tutorial or lab then;
4. the room is a lecture room, big enough, and free: no timetabled session,
   no other booking (a room is picked automatically when none is named);
5. very large events and the auditorium go to the timetable office.

A request that passes is booked at once; one that fails comes back with the
checks it failed and alternatives that pass them (another room at the same
time, or the same room at another time), and the booking rules it relates to.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from .solver import Meeting, Room, SemesterCalendar, minutes

BIG_EVENT = 150


class ClubRequest(BaseModel):
    club: str
    activity: str
    date: str  # YYYY-MM-DD
    start: str  # HH:MM
    end: str
    attendees: int
    cohorts: list[str] = Field(default_factory=list)
    room: str | None = None
    requested_by: str = ""


class Check(BaseModel):
    name: str
    ok: bool
    detail: str


class ClubDecision(BaseModel):
    id: str
    request: ClubRequest
    status: str  # booked | needs_approval | rejected
    room: str | None
    day: str
    week: int | None
    checks: list[Check]
    alternatives: list[dict] = Field(default_factory=list)
    rules: list[dict] = Field(default_factory=list)  # {id, title, source}
    decided_at: str = ""


def semester_week(d: date, start: date, weeks: int) -> int | None:
    w = (d - start).days // 7 + 1
    return w if 1 <= w <= weeks else None


def _overlap(a1: int, b1: int, a2: int, b2: int) -> bool:
    return a1 < b2 and a2 < b1


def _working_days(a: date, b: date) -> int:
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        n += d.weekday() < 6  # Mon-Sat are working days here
    return n


class ClubDesk:
    def __init__(self, calendar: SemesterCalendar, rooms: list[Room], semester_start: date,
                 notice_days: int = 2, auditorium_notice: int = 5) -> None:
        self.cal = calendar
        self.rooms = {r.id: r for r in rooms}
        self.start = semester_start
        self.notice_days = notice_days
        self.auditorium_notice = auditorium_notice

    def _busy(self, room: str, day: str, a: int, b: int, half: int | None, meetings: list[Meeting],
              bookings: list[ClubDecision], on: date) -> str | None:
        for mt in meetings:
            if room in mt.rooms and mt.day == day and _overlap(a, b, minutes(mt.start), minutes(mt.end)) and (
                    half is None or mt.half == "full" or mt.half == f"H{half}"):
                return f"{mt.course} {mt.label} ({mt.start}-{mt.end})"
        for bk in bookings:
            if bk.status == "booked" and bk.room == room and bk.request.date == on.isoformat() and _overlap(
                    a, b, minutes(bk.request.start), minutes(bk.request.end)):
                return f"{bk.request.club} ({bk.request.start}-{bk.request.end})"
        return None

    def _members_busy(self, cohorts: list[str], day: str, a: int, b: int, half: int | None,
                      meetings: list[Meeting]) -> list[str]:
        out = []
        for mt in meetings:
            if set(mt.cohorts) & set(cohorts) and mt.day == day and _overlap(a, b, minutes(mt.start), minutes(mt.end)) and (
                    half is None or mt.half == "full" or mt.half == f"H{half}"):
                out.append(f"{mt.course} {mt.label} {mt.start}-{mt.end}")
        return sorted(set(out))

    def _free_rooms(self, req: ClubRequest, day: str, a: int, b: int, half: int | None, meetings, bookings, on) -> list[str]:
        fits = sorted((r for r in self.rooms.values() if r.type == "lecture" and r.capacity >= req.attendees),
                      key=lambda r: r.capacity)
        return [r.id for r in fits if not self._busy(r.id, day, a, b, half, meetings, bookings, on)]

    def check(self, req: ClubRequest, meetings: list[Meeting], bookings: list[ClubDecision],
              today: date | None = None, rules: list[dict] | None = None) -> ClubDecision:
        today = today or date.today()
        on = datetime.strptime(req.date, "%Y-%m-%d").date()
        day = on.strftime("%a")
        week = semester_week(on, self.start, self.cal.weeks)
        half = None if week is None else (1 if week <= self.cal.weeks // 2 else 2)
        a, b = minutes(req.start), minutes(req.end)
        checks: list[Check] = []

        windows = [w for w in self.cal.club_hours if day in w.days]
        inside = any(minutes(w.start) <= a and b <= minutes(w.end) for w in windows) and a < b
        hours = "; ".join(f"{', '.join(w.days)} {w.start}-{w.end}" for w in self.cal.club_hours)
        checks.append(Check(name="Club hours", ok=inside,
                            detail="inside club hours" if inside else f"club activities run {hours}"))

        room = req.room
        auditorium = (room or "").lower().startswith("audi")
        need = self.auditorium_notice if auditorium else self.notice_days
        have = _working_days(today, on) if auditorium else (on - today).days
        checks.append(Check(name="Notice", ok=have >= need,
                            detail=f"{have} {'working ' if auditorium else ''}day(s) ahead; "
                                   f"{need} needed{' for the auditorium' if auditorium else ''}"))

        clash = self._members_busy(req.cohorts, day, a, b, half, meetings) if req.cohorts else []
        checks.append(Check(name="Members free", ok=not clash,
                            detail="no class for the members' programmes then" if req.cohorts and not clash else
                            ("no programmes named, so not checked" if not req.cohorts else
                             f"members have {'; '.join(clash[:3])}")))

        free = self._free_rooms(req, day, a, b, half, meetings, bookings, on) if inside else []
        if room:
            r = self.rooms.get(room)
            if r is None and not auditorium:
                checks.append(Check(name="Room", ok=False, detail=f"there is no room {room}"))
            elif r is not None:
                busy = self._busy(room, day, a, b, half, meetings, bookings, on)
                problems = ([f"{room} is a {r.type} lab"] if r.type != "lecture" else []) + \
                           ([f"seats {r.capacity}, {req.attendees} expected"] if r.capacity < req.attendees else []) + \
                           ([f"booked for {busy}"] if busy else [])
                checks.append(Check(name="Room", ok=not problems,
                                    detail="; ".join(problems) or f"{room} is free and seats {r.capacity}"))
            else:
                checks.append(Check(name="Room", ok=True, detail="the auditorium is allocated by the academic office"))
        else:
            room = free[0] if free else None
            checks.append(Check(name="Room", ok=room is not None or not inside,
                                detail=f"{room} is free and seats {self.rooms[room].capacity}" if room else
                                "not checked: the time is outside club hours" if not inside else
                                f"no free lecture room seats {req.attendees} then"))

        needs_office = auditorium or req.attendees > BIG_EVENT
        if needs_office:
            checks.append(Check(name="Office approval", ok=True,
                                detail="the auditorium and events over 150 people are approved by the timetable office"))
        ok = all(c.ok for c in checks)
        decision = ClubDecision(id=uuid.uuid4().hex[:8], request=req, room=room, day=day, week=week, checks=checks,
                                status=("needs_approval" if needs_office else "booked") if ok else "rejected",
                                rules=rules or [], decided_at=datetime.now().isoformat(timespec="seconds"))
        if not ok:
            decision.alternatives = self.alternatives(req, meetings, bookings, today)
        return decision

    def alternatives(self, req: ClubRequest, meetings: list[Meeting], bookings: list[ClubDecision],
                     today: date, limit: int = 4) -> list[dict]:
        """Nearby slots that pass every check: same time other rooms first, then other times and days."""
        out: list[dict] = []
        on = datetime.strptime(req.date, "%Y-%m-%d").date()
        length = max(30, minutes(req.end) - minutes(req.start))
        for shift in range(0, 8):
            d = on + timedelta(days=shift)
            if (d - today).days < self.notice_days:
                continue
            day = d.strftime("%a")
            week = semester_week(d, self.start, self.cal.weeks)
            half = None if week is None else (1 if week <= self.cal.weeks // 2 else 2)
            starts = [minutes(req.start)] if shift == 0 else []
            for w in self.cal.club_hours:
                if day in w.days:
                    starts += list(range(minutes(w.start), minutes(w.end) - length + 1, 30))
            for a in dict.fromkeys(starts):
                b = a + length
                if not any(day in w.days and minutes(w.start) <= a and b <= minutes(w.end) for w in self.cal.club_hours):
                    continue
                if req.cohorts and self._members_busy(req.cohorts, day, a, b, half, meetings):
                    continue
                rooms = self._free_rooms(req, day, a, b, half, meetings, bookings, d)
                if req.room and req.room in rooms:
                    rooms = [req.room]
                if rooms:
                    out.append({"date": d.isoformat(), "day": day, "start": f"{a // 60:02d}:{a % 60:02d}",
                                "end": f"{b // 60:02d}:{b % 60:02d}", "room": rooms[0]})
                    if len(out) >= limit:
                        return out
        return out
