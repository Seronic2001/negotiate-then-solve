"""Stakeholder simulators with hidden flexibility (proposal Sections 8.6, 12).

A simulated faculty member states a constraint as absolute, but privately
knows which other times would really work (``windows``), whether a room
without the requested equipment would do (``room_flexible``), whether they
volunteer an alternative when asked (``reveal``) and whether they answer at
all (``responsive``). Decisions are scripted, so outcomes are reproducible
and the oracle can be computed with all of this known.

The reply text is either a template (no API calls) or written by the
simulator LLM (Flash-Lite) from the scripted decision, in which case the
negotiator only sees text and must parse it (``structured=False``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from .corpus import FULL_DAY, hour
from .instance import Instance
from .negotiation import Message, Reply
from .schemas import Placement


class Window(BaseModel):
    days: list[str] | None = None
    slots: list[int] | None = None

    def covers(self, day: str, slots: range) -> bool:
        return (self.days is None or day in self.days) and (self.slots is None or set(slots) <= set(self.slots))

    def text(self) -> str:
        days = " or ".join(FULL_DAY[d] for d in self.days) if self.days else "any day"
        if not self.slots:
            return days
        return f"{days} from {hour(min(self.slots))} to {hour(max(self.slots) + 1)}"


class Profile(BaseModel):
    """Hidden truth about one stakeholder in a scenario."""

    owner: str
    windows: list[Window] = Field(default_factory=list)  # times that really work, beyond the stated ones
    needs: list[str] = Field(default_factory=list)  # equipment they really need
    room_flexible: bool = False  # would accept a room without that equipment
    reveal: bool = True  # volunteers a window when no offer fits
    responsive: bool = True


class _Voiced(BaseModel):
    text: str


VOICE_PROMPT = """You play a university faculty member answering a message from the timetable
office. Write a short, natural reply (1-2 sentences) that says exactly what you
are told to say and nothing else. Do not invent other conditions."""


@dataclass
class Simulator:
    instance: Instance
    profile: Profile
    client: object | None = None  # voices replies with the LLM when set
    structured: bool = True  # hand the negotiator the decision, not just text
    revealed: bool = False
    log: list[Reply] = field(default_factory=list)

    def acceptable(self, sid: str, p: Placement) -> bool:
        session = next(s for s in self.instance.sessions if s.id == sid)
        span = range(p.slot, p.slot + session.duration)
        if not any(w.covers(p.day, span) for w in self.profile.windows):
            return False
        room = self.instance.room_by_id[p.room]
        needs = set(self.profile.needs) | set(session.equipment)
        return self.profile.room_flexible or needs <= set(room.equipment)

    def respond(self, message: Message) -> Reply:
        if not self.profile.responsive:
            reply = Reply(decision="no_reply")
            self.log.append(reply)
            return reply
        fits = [o for o in message.offers if o.placements and all(
            self.acceptable(s, p) for s, p in o.placements.items())]
        if fits:
            reply = Reply(decision="accept", choice=fits[0].key)
            say = f"You accept option {fits[0].key}."
        elif self.profile.reveal and self.profile.windows and not self.revealed:
            w = self.profile.windows[0]
            self.revealed = True
            reply = Reply(decision="counter", counter_days=w.days, counter_slots=w.slots)
            say = f"None of the options work, but {w.text()} would work for you."
        else:
            reply = Reply(decision="reject")
            say = "None of the options work for you, and you have nothing else to suggest."
        reply.text = self._voice(reply, say, message)
        if not self.structured:
            reply = Reply(text=reply.text)
        self.log.append(reply)
        return reply

    def _voice(self, reply: Reply, say: str, message: Message) -> str:
        if self.client is None:
            if reply.decision == "accept":
                return f"Option {reply.choice} works for me, thanks."
            if reply.decision == "counter":
                return f"Sorry, those don't suit me, but {self.profile.windows[0].text()} would work."
            return "Sorry, none of those work for me."
        me = self.instance.faculty_by_id.get(self.profile.owner)
        prompt = (f"You are {me.name if me else self.profile.owner}.\nThe message you received:\n"
                  f"<message>\n{message.text}\n</message>\n\nWhat to say: {say}")
        return self.client.generate(VOICE_PROMPT, prompt, _Voiced, temperature=0.7).text
