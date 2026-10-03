"""Preferences and changes for the semester timetable, from plain words.

    "Girish Varma prefers not to teach before 10 am"
    "UG1 CSE students would like no classes after 5 pm on Saturday"
    "Prasad Krishnan is unavailable on Fridays"
    "CS1.301 should be in the morning"
    "Room H105 is closed on Tuesdays for renovation"

Who it is about comes from the offering document (faculty names, course
codes and names, programmes and years); days and times from the words.
"can't", "unavailable", "away", "must" make it a hard rule; anything else is
a preference the solver weighs.
"""

from __future__ import annotations

import re
import uuid

from .offerings import OfferingDoc
from .solver import Preference, Room, Window, faculty_key

DAYS = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat"}
DAY_RE = re.compile(r"\b(mon|tue|tues|wed|thu|thur|thurs|fri|sat)(?:day|nesday|sday|urday|rsday|s)?s?\b", re.IGNORECASE)
HARD = re.compile(r"\b(can'?t|cannot|unavailable|not available|away|must|on leave|closed|shut)\b", re.IGNORECASE)
AVOID = re.compile(r"\b(no|not|avoid|without|free|don'?t|never|rather not|can'?t|cannot|unavailable|away|"
                   r"on leave|closed|shut)\b", re.IGNORECASE)
YEAR = {"1": "I", "2": "II", "3": "III", "4": "IV", "5": "V", "first": "I", "second": "II", "third": "III",
        "fourth": "IV", "fifth": "V"}
BRANCHES = ("CSE", "CSD", "ECE", "ECD", "CND", "CLD", "CHD", "CGD")


class Parsed:
    def __init__(self) -> None:
        self.preferences: list[Preference] = []
        self.closures: list[tuple[str, Window]] = []
        self.summary: list[str] = []
        self.error: str | None = None


def _clock(h: str, m: str | None, ampm: str | None) -> str:
    hour = int(h)
    if ampm and ampm.lower().startswith("p") and hour < 12:
        hour += 12
    elif not ampm and 1 <= hour <= 7:
        hour += 12  # "after 5" in a timetable means 5 pm
    return f"{hour:02d}:{int(m or 0):02d}"


_T = r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?"


def _window(text: str) -> tuple[str | None, str | None, str]:
    t = text.lower()
    if m := re.search(r"between\s+" + _T + r"\s+(?:and|to|-)\s+" + _T, t):
        a = _clock(m[1], m[2], m[3] or m[6])
        return a, _clock(m[4], m[5], m[6]), f"between {a} and {_clock(m[4], m[5], m[6])}"
    if m := re.search(r"\b(?:before|until|till|earlier than)\s+" + _T, t):
        return None, _clock(*m.groups()), f"before {_clock(*m.groups())}"
    if m := re.search(r"\b(?:after|from|later than)\s+" + _T, t):
        return _clock(*m.groups()), None, f"after {_clock(*m.groups())}"
    if re.search(r"\bmornings?\b", t):
        return None, "13:05", "in the morning"
    if re.search(r"\bafternoons?\b", t):
        return "14:00", "18:40", "in the afternoon"
    if re.search(r"\bevenings?\b|\blate\b", t):
        return "17:00", None, "in the evening"
    if m := re.search(r"\bslot\s*([1-6])\b", t):
        slots = {"1": ("08:30", "09:55"), "2": ("10:05", "11:30"), "3": ("11:40", "13:05"), "4": ("14:00", "15:25"),
                 "5": ("15:35", "17:00"), "6": ("17:10", "18:40")}[m[1]]
        return slots[0], slots[1], f"in slot {m[1]}"
    if re.search(r"8[:.]30", t):
        return "08:30", "09:55", "in the 8:30 slot"
    return None, None, ""


def _days(text: str) -> list[str] | None:
    found = []
    for m in DAY_RE.finditer(text):
        d = DAYS.get(m[1][:3].lower())
        if d and d not in found:
            found.append(d)
    if re.search(r"\bweekends?\b", text, re.IGNORECASE):
        found.append("Sat")
    return found or None


def _cohorts(text: str, doc: OfferingDoc) -> list[str]:
    t = text.upper()
    year = None
    if m := re.search(r"\bUG\s?([1-5])\b", t):
        year = YEAR[m[1]]
    elif m := re.search(r"\b(FIRST|SECOND|THIRD|FOURTH|FIFTH|[1-5](?:ST|ND|RD|TH)?)[- ]YEARS?\b", t):
        year = YEAR.get(m[1].lower()[:1] if m[1][0].isdigit() else m[1].lower())
    pg = re.search(r"\bM\.?\s?TECH|\bPG\b", t) is not None
    branches = [b for b in BRANCHES if re.search(rf"\b{b}\b", t)]
    if not year and not pg:
        return []
    out = []
    for c in doc.cohorts:
        name = c.name.upper()
        if pg != ("M.TECH" in name or "MTECH" in name):
            continue
        if year and not re.search(rf"\b{year} YEAR\b", name):
            continue
        if branches and not any(b in name for b in branches):
            continue
        out.append(c.id)
    return out


def _faculty(text: str, doc: OfferingDoc) -> list[str]:
    names = {faculty_key(f): f for c in doc.courses.values() for f in c.faculty if f}
    t = faculty_key(text)
    hits = [full for key, full in names.items() if len(key) > 4 and key in t]
    if not hits:  # a surname alone, when it is unique
        words = set(re.findall(r"[a-z]{4,}", t))
        by_last = {}
        for key, full in names.items():
            by_last.setdefault(key.split()[-1], []).append(full)
        hits = [v[0] for w, v in by_last.items() if w in words and len(v) == 1]
    return sorted(set(hits), key=len, reverse=True)[:1]


def _courses(text: str, doc: OfferingDoc) -> list[str]:
    codes = [c for c in re.findall(r"\b[A-Z]{2}\d\.\d{3}[a-z]?\b", text) if c in doc.courses]
    if codes:
        return codes
    t = text.lower()
    return [c.code for c in sorted(doc.courses.values(), key=lambda c: -len(c.name))
            if len(c.name) > 6 and c.name.lower() in t][:1]


def parse(text: str, doc: OfferingDoc, rooms: list[Room], source: str = "") -> Parsed:
    out = Parsed()
    days = _days(text)
    start, end, when = _window(text)
    hard = bool(HARD.search(text))
    room_ids = {r.id.lower(): r.id for r in rooms}
    room = next((room_ids[w.lower()] for w in re.findall(r"[A-Za-z0-9-]+", text) if w.lower() in room_ids), None)
    if room and re.search(r"\b(closed|shut|unavailable|renovation|maintenance|out of service)\b", text, re.IGNORECASE):
        w = Window(days=days or ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"], start=start or "00:00", end=end or "23:59",
                   reason=text)
        out.closures.append((room, w))
        out.summary.append(f"close {room} {'on ' + ', '.join(w.days) if days else 'all week'}"
                           f"{' ' + when if when else ''}")
        return out
    if not days and not start and not end:
        out.error = "Say when: a day (\"on Fridays\") or a time (\"before 10 am\", \"in the evening\")."
        return out
    avoid = bool(AVOID.search(text))
    mode = "avoid" if avoid else "prefer"
    targets: list[tuple[str, str, str]] = []
    for f in _faculty(text, doc):
        targets.append(("faculty", f, f))
    if not targets:
        for code in _courses(text, doc):
            targets.append(("course", code, f"{code} {doc.courses[code].name}"))
    if not targets:
        for cid in _cohorts(text, doc):
            name = next(c.name for c in doc.cohorts if c.id == cid)
            targets.append(("cohort", cid, name))
    if not targets:
        out.error = "Who is this about? Name a faculty member, a course (code or name) or a programme and year (\"UG1 CSE\")."
        return out
    for kind, who, label in targets:
        p = Preference(id=uuid.uuid4().hex[:8], target=kind, who=who, mode=mode, days=days, start=start, end=end,
                       hard=hard, weight=3, text=text.strip(), source=source)
        out.preferences.append(p)
        out.summary.append(f"{'must' if hard else 'prefer to'} {'avoid' if mode == 'avoid' else 'keep'} "
                           f"{label}{' on ' + ', '.join(days) if days else ''}{' ' + when if when else ''}"
                           f"{' (hard)' if hard else ''}")
    return out
