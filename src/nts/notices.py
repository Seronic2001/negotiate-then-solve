"""Notices to the people a committed change affects, built from the timetables, never from what the agent wrote.

    notices(before, after, actor="F-103")   # {"F-106": ["Your Algorithms lecture (Section 2), week 6: moves ..."]}

Whoever's class moved or is not held, other than the person who asked, is told what changed and when. No
reason is given: the request and what was said about it stay between the requester, the agent and the
office (a moved class's teacher learns only that the timetable changed). Each section's class representative
("rep:" + the section's id) is told the same of the section's classes, the requester's own included.
"""

from __future__ import annotations

from nts.state import World
from nts.tools.draft import REP
from nts.tools.names import FULL_DAY, hour


def notices(before: World, after: World, actor: str) -> dict[str, list[str]]:
    """One line per person and change; the same change in several weeks is one line ("weeks 7 to 16: ...")."""
    inst = after.instance
    said: dict[str, dict[tuple[str, str], list[int | None]]] = {}  # person -> (what, change) -> weeks, in order
    for w in sorted(after.timetables, key=lambda x: 0 if x is None else x):
        new, old = after.timetables[w], before.timetable(w)
        if old is None or (w in before.timetables and before.timetables[w] is new):
            continue
        for sid, p in sorted(new.assignment.items()):
            s = inst.session_by_id[sid]
            q = old.assignment.get(sid)
            if sid in new.cancelled and sid not in old.cancelled:
                change = "not held."
            elif q is not None and q != p and sid not in new.cancelled:
                change = f"moves from {_at(inst, q)} to {_at(inst, p)}."
            else:
                continue
            course = f"{inst.course_title(s.course)} {s.kind.value}"
            if s.faculty != actor:
                groups = ", ".join(inst.group_by_id[g].name for g in s.groups)
                said.setdefault(s.faculty, {}).setdefault((f"Your {course} ({groups})", change), []).append(w)
            teacher = inst.faculty_by_id[s.faculty].name if s.faculty in inst.faculty_by_id else "its teacher"
            for g in s.groups:
                said.setdefault(f"{REP}{g}", {}).setdefault((f"Your {course} with {teacher}", change), []).append(w)
    return {person: [f"{what}, {_weeks(weeks)}: {change}" for (what, change), weeks in lines.items()]
            for person, lines in said.items()}


def _weeks(weeks: list[int | None]) -> str:
    """"every week", "week 6", "weeks 7 to 16", or "weeks 6, 8 and 9"."""
    if None in weeks:  # the semester timetable, and the weeks that have their own: every week
        return "every week"
    ws = sorted(weeks)
    if len(ws) == 1:
        return f"week {ws[0]}"
    if ws == list(range(ws[0], ws[-1] + 1)):
        return f"weeks {ws[0]} to {ws[-1]}"
    return "weeks " + ", ".join(map(str, ws[:-1])) + f" and {ws[-1]}"


def _at(inst, p) -> str:
    return f"{FULL_DAY[p.day]} {hour(p.slot)} in {inst.room_by_id[p.room].name}"
