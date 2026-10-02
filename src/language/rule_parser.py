"""Offline parser: a rule-based stand-in for System Two, so the portal runs
without an API key. It returns the same ``ParseOutput`` and goes through the
same deterministic post-processing (tiers, authority, validation), so every
downstream layer behaves as it would with the LLM. It covers the common
request shapes of the corpus; anything it cannot read becomes a
clarification rather than a guess.
"""

from __future__ import annotations

import re

from core.instance import Instance, SessionKind
from core.schemas import Request

from .corpus import INJECTIONS
from .parsing import DraftConstraint, ParseOutput, ParseResult, postprocess

DAY_WORDS = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}
_DAY = re.compile(r"\b(mon|tue|tues|wed|wednes|thu|thur|thurs|fri|sat|satur|sun)(?:day)?s?\b", re.I)
_RANGE = re.compile(r"\b(mon|tue|wed|thu|fri)\w*\s*(?:to|-|–|through|till|until)\s*(mon|tue|wed|thu|fri)\w*", re.I)
_WEEKS = re.compile(r"\bweeks?\s+(\d{1,2})(?:\s*(?:-|–|to|and)\s*(\d{1,2}))?", re.I)
_TIME = re.compile(r"\b(\d{1,2})(?::\d\d)?\s*(am|pm)\b", re.I)
_INJECTION = re.compile(r"(?im)^.*(ignore (all |previous )|system:|admin mode|assistant[,:]|approve all|"
                        r"publish (it |immediately|now)|override|</message>).*$")
UNAVAILABLE = re.compile(r"\b(conference|away|leave|unavailable|can't|cannot|can not|won't be|not be available|"
                         r"appointment|duty|out of station|travelling|traveling|not available)\b", re.I)
WISH = re.compile(r"\b(prefer|rather|if possible|would like|avoid|try to|keep .* free|where possible)\b", re.I)
ONLY = re.compile(r"\b(only|limit(ed)? to|restrict|keep my (lectures|classes|teaching) to|all my teaching on)\b", re.I)
AVOID = re.compile(r"\b(no classes|not teach|avoid|free|nothing before|don't schedule|do not schedule|rather not)\b", re.I)
QUESTION = re.compile(r"\b(rule|allowed|permitted|permissible|policy|who (has|needs) to approve|how many|"
                      r"can classes|is it ok)\b", re.I)
OUT_OF_SCOPE = re.compile(r"\b(auditorium|wifi|wi-fi|salary|projector|exam results|fest|book the)\b", re.I)
VAGUE = re.compile(r"\b(a few days|couple of days|soon|next month|later this semester|some days|fewer early)\b", re.I)
EQUIPMENT = {"gpu": "gpu", "graphics": "gpu", "router": "routers", "networking": "routers", "electronic": "electronics"}
SWAP = re.compile(r"\b(swap|swapp\w*|exchange|trade|switch)\b|"
                  r"\btake my\b.*\b(and )?I (take|teach|cover) (their|his|her)\b", re.I)
_TITLE_WORD = re.compile(r"^(dr|prof|professor|mr|ms|mrs)\.?$", re.I)


def surname(name: str) -> str:
    parts = [p for p in re.split(r"[\s.]+", name) if p and not _TITLE_WORD.match(p)]
    return parts[-1] if parts else name


def _slot(hour: int, ampm: str) -> int:
    h = hour % 12 + (12 if ampm.lower() == "pm" else 0)
    return h - 9


class RuleParser:
    def __init__(self, instance: Instance) -> None:
        self.instance = instance
        cal = instance.calendar
        lunch = cal.lunch_slot if cal.lunch_slot is not None else cal.slots_per_day // 2
        self.morning = list(range(lunch))
        self.afternoon = list(range(lunch + 1, cal.slots_per_day))

    # -- reading the text ---------------------------------------------------------

    def days(self, text: str) -> list[str] | None:
        order = self.instance.calendar.days
        if m := _RANGE.search(text):
            a, b = DAY_WORDS[m[1][:3].lower()], DAY_WORDS[m[2][:3].lower()]
            if a in order and b in order and order.index(a) <= order.index(b):
                return order[order.index(a): order.index(b) + 1]
        found = [DAY_WORDS[d[:3].lower()] for d in _DAY.findall(text)]
        days = [d for d in order if d in found]
        return days or None

    def weeks(self, text: str) -> list[int] | None:
        if m := _WEEKS.search(text):
            a = int(m[1])
            b = int(m[2]) if m[2] else a
            return list(range(min(a, b), max(a, b) + 1))
        return None

    def slots(self, text: str) -> list[int] | None:
        low = text.lower()
        spd = self.instance.calendar.slots_per_day
        if m := re.search(r"before\s+(\d{1,2})(?::\d\d)?\s*(am|pm)", low):
            return list(range(0, max(1, _slot(int(m[1]), m[2]))))
        if m := re.search(r"after\s+(\d{1,2})(?::\d\d)?\s*(am|pm)", low):
            return list(range(min(spd - 1, _slot(int(m[1]), m[2])), spd))
        if re.search(r"after lunch|afternoon", low):
            return self.afternoon
        if "morning" in low:
            return self.morning
        times = [_slot(int(h), ap) for h, ap in _TIME.findall(low)]
        times = [t for t in times if 0 <= t < spd]
        return sorted(set(times)) or None

    def sessions_named(self, text: str, faculty: str | None) -> list[str]:
        low = text.lower()
        mine = [s for s in self.instance.sessions if faculty is None or s.faculty == faculty]
        named = [s for s in mine if self.instance.course_title(s.course).lower() in low]
        if re.search(r"\b(practical|lab session|lab)\b", low):
            named = [s for s in (named or mine) if s.kind == SessionKind.PRACTICAL]
        return [s.id for s in named]

    def other_faculty(self, text: str, sender: str) -> str | None:
        low = text.lower()
        for f in self.instance.faculty:
            if f.id != sender and f.name.lower() in low:
                return f.id
        return None

    def mentioned(self, text: str, sender: str) -> list[str]:
        """Other faculty members the text names: by full name, else every one
        whose surname appears ("Dr. Rao" may fit two people)."""
        if found := self.other_faculty(text, sender):
            return [found]
        low = text.lower()
        return [f.id for f in self.instance.faculty
                if f.id != sender and re.search(rf"\b{re.escape(surname(f.name).lower())}\b", low)]

    def colleague(self, text: str, sender: str) -> str | None:
        hits = self.mentioned(text, sender)
        return hits[0] if len(hits) == 1 else None

    # -- parsing -----------------------------------------------------------------------

    def parse(self, request: Request) -> ParseResult:
        return postprocess(self.instance, request, self.read(request))

    def read(self, request: Request) -> ParseOutput:
        text = _INJECTION.sub("", request.raw_text)
        for inj in INJECTIONS:
            text = text.replace(inj, "")
        low = text.lower()
        sender = request.sender_id
        role = request.role.value

        if OUT_OF_SCOPE.search(low):
            return ParseOutput(request_type="out_of_scope", action="out_of_scope")
        if role == "student" and re.search(r"\bclash|overlap|same time\b", low):
            return ParseOutput(request_type="clash_report", action="investigate")
        if "?" in text and QUESTION.search(low) and not re.search(r"\b(could you|can you|please)\b", low):
            return ParseOutput(request_type="policy_question", action="answer")

        if role != "student" and SWAP.search(low) and self.mentioned(text, sender):
            # which two sessions is decided against the timetable (agents.swap), not here
            return ParseOutput(request_type="swap", action="compile")

        days, weeks, slots = self.days(text), self.weeks(text), self.slots(text)
        other = self.other_faculty(text, sender)
        scope_kind, scope_id = ("faculty", other) if other else ("faculty", sender)

        # rooms: a lab in-charge reporting an outage
        if role == "lab_incharge":
            lab = next((r for r in self.instance.rooms if r.name.lower() in low or r.id.lower() in low), None)
            if lab is None:
                return self._clarify("room_issue", ["room"], "Which room is affected?")
            if weeks is None and days is None:
                return self._clarify("room_issue", ["weeks"], f"Which weeks is {lab.name} unavailable?")
            return self._compile("room_issue", [DraftConstraint(
                type="unavailable", hard=True, scope_kind="room", scope_id=lab.id, days=days, weeks=weeks)])

        # equipment a session needs
        needs = sorted({v for k, v in EQUIPMENT.items() if k in low})
        if needs:
            sessions = self.sessions_named(text, None if other else sender)
            if other:
                sessions = [s.id for s in self.instance.sessions if s.faculty == other and
                            s.kind == SessionKind.PRACTICAL] or sessions
            if not sessions:
                return self._clarify("room_issue", ["session"], "Which of your classes needs this equipment?")
            drafts = [DraftConstraint(type="require_room", hard=True, scope_kind="session", scope_id=sessions[0],
                                      equipment=needs, justification="stated")]
            if days or slots:
                drafts.append(DraftConstraint(type="prefer", hard=True, scope_kind="session", scope_id=sessions[0],
                                              days=days, slots=slots, weeks=weeks))
            return self._compile("room_issue", drafts)

        if VAGUE.search(low) or (UNAVAILABLE.search(low) and not days and not weeks):
            missing = [m for m, v in (("days", days), ("weeks", weeks), ("slots", slots)) if v is None][:2]
            return self._clarify("unavailability" if UNAVAILABLE.search(low) else "preference", missing or ["days"],
                                 "Could you tell me which " + " and ".join(missing or ["days"]) + " you mean?")

        if UNAVAILABLE.search(low):
            return self._compile("unavailability", [DraftConstraint(
                type="unavailable", hard=True, scope_kind=scope_kind, scope_id=scope_id, days=days,
                slots=slots, weeks=weeks, justification="stated" if re.search(r"\b(because|due to|conference|"
                                                                              r"appointment|duty)\b", low) else "none")])

        # a specific placement ("schedule my lecture at 1 pm on Friday", "4 lectures back-to-back")
        if re.search(r"\b(schedule|move|put|shift|stack)\b", low) and (days or slots):
            sessions = self.sessions_named(text, scope_id if scope_kind == "faculty" else None)
            if re.search(r"back.to.back|in a row|straight|consecutive|without (any )?breaks?", low):
                return self._compile("preference", [DraftConstraint(
                    type="prefer", hard=True, scope_kind=scope_kind, scope_id=scope_id, days=days,
                    slots=slots or self.morning)])
            target = ("session", sessions[0]) if sessions else (scope_kind, scope_id)
            return self._compile("preference", [DraftConstraint(
                type="prefer", hard=True, scope_kind=target[0], scope_id=target[1], days=days, slots=slots)])

        if days or slots:
            hard = not WISH.search(low) and bool(re.search(r"\b(must|need|has to|have to|cannot)\b", low))
            if ONLY.search(low) and days and not AVOID.search(low):
                return self._compile("preference", [DraftConstraint(
                    type="prefer", hard=hard, scope_kind=scope_kind, scope_id=scope_id, days=days, slots=slots)])
            return self._compile("preference", [DraftConstraint(
                type="avoid", hard=hard, scope_kind=scope_kind, scope_id=scope_id, days=days, slots=slots)])

        return self._clarify("preference", ["days", "slots"],
                             "Could you tell me which days and times you mean?")

    @staticmethod
    def _compile(kind: str, drafts: list[DraftConstraint]) -> ParseOutput:
        return ParseOutput(request_type=kind, action="compile", constraints=drafts)

    @staticmethod
    def _clarify(kind: str, missing: list[str], question: str) -> ParseOutput:
        return ParseOutput(request_type=kind, action="clarify", missing=missing, clarifying_question=question)
