"""Grounded, contrastive, private explanations (proposal Section 8.7).

A conflict is turned into numbered facts: the constraints in the MUS, the
rules they come from, which rooms have the equipment, the solver-verified
options and the ledger history. Explanations are built only from these:

* ``template``: deterministic sentences, one per fact (no LLM);
* ``grounded``: the LLM writes claims, each citing fact IDs; a verifier drops
  claims that cite nothing, cite unknown facts, or mention a day, number or
  name that is not in the facts they cite;
* ``free`` (ablation A3): the LLM writes freely from the raw requests; the
  same checks then measure how many sentences can be traced.

Facts name the constraint, never the private reason, so leakage can only
come from the model; ``leaks`` measures it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel

from core.instance import Instance
from core.schemas import Constraint, ConstraintType, Placement, Tier
from language.corpus import FULL_DAY, hour
from language.llm import LLMError
from language.paraphrase import FidelityCheck

from .policy import _CLOCK, _clock

TIER_NAME = {
    Tier.PHYSICAL: "physical", Tier.POLICY: "institute policy", Tier.COMMITMENT: "institutional commitment",
    Tier.VERIFIED_UNAVAILABILITY: "verified unavailability", Tier.OPERATIONAL: "operational requirement",
    Tier.PREFERENCE: "preference",
}
PRIVATE_TERMS = ("medical", "hospital", "doctor", "family", "surgery", "illness", "sick", "pregnan",
                 "funeral", "clinical", "therapy", "health", "personal matter", "wedding")


@dataclass(frozen=True)
class Fact:
    id: str
    text: str


@dataclass(frozen=True)
class OptionView:
    """One solver-verified option as the recipient sees it."""

    key: str
    placements: dict[str, Placement]
    drop: tuple[str, ...]


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


def _slots(slots: list[int]) -> str:
    slots = sorted(slots)
    if slots == list(range(slots[0], slots[-1] + 1)) and len(slots) > 1:
        return f"from {hour(slots[0])} to {hour(slots[-1] + 1)}"
    return "at " + ", ".join(hour(s) for s in slots)


def _when(instance: Instance, c: Constraint) -> str:
    parts = []
    if c.when.days:
        parts.append("on " + ", ".join(FULL_DAY[d] for d in c.when.days))
    if c.when.slots is not None:
        lunch = instance.calendar.lunch_slot
        afternoon = list(range(lunch + 1, instance.calendar.slots_per_day)) if lunch is not None else None
        parts.append("in the afternoon" if sorted(c.when.slots) == afternoon else _slots(c.when.slots))
    if c.when.weeks:
        w = sorted(c.when.weeks)
        parts.append(f"in week {w[0]}" if len(w) == 1 else f"in weeks {w[0]}-{w[-1]}")
    return " ".join(parts)


def session_name(instance: Instance, sid: str) -> str:
    s = next((x for x in instance.sessions if x.id == sid), None)
    if s is None:
        return sid
    return f"the {instance.course_title(s.course)} {s.kind.value} ({sid})"


def placement_text(instance: Instance, p: Placement) -> str:
    room = instance.room_by_id[p.room].name if p.room in instance.room_by_id else p.room
    return f"{FULL_DAY[p.day]} at {hour(p.slot)} in {room}"


def describe(instance: Instance, c: Constraint) -> str:
    """One constraint in plain words: who, what, when, tier. Never the reason."""
    who = instance.faculty_by_id[c.owner].name if c.owner in instance.faculty_by_id else (
        "The lab in-charge" if c.owner and c.owner.startswith("S-LAB") else "The institute")
    s = c.scope
    what = (session_name(instance, s.session) if s.session else
            f"{instance.room_by_id[s.room].name}" if s.room and s.room in instance.room_by_id else
            f"{instance.group_by_id[s.group].name}'s classes" if s.group else
            f"the {instance.course_title(s.course)} classes" if s.course else
            "their classes" if s.faculty and s.faculty == c.owner else "all classes")
    when = _when(instance, c)
    if c.type == ConstraintType.UNAVAILABLE:
        body = f"{what[0].upper() + what[1:]} is unavailable {when}" if s.room else f"{who} is unavailable {when}"
    elif c.type == ConstraintType.PREFER:
        body = f"{who} {'needs' if c.hard else 'would like'} {what} {when}"
    elif c.type == ConstraintType.AVOID:
        body = f"{who} {'cannot have' if c.hard else 'would rather not have'} {what} {when}"
    elif c.type == ConstraintType.REQUIRE_ROOM:
        need = (", ".join(c.room.equipment) if c.room and c.room.equipment else
                " or ".join(instance.room_by_id[r].name for r in (c.room.rooms or [])) if c.room else "")
        body = f"{who} needs {what} in a room with {need}" if c.room and c.room.equipment else \
            f"{who} needs {what} in {need}"
    else:
        body = f"No one may teach more than {c.limit} hours in a row"
    return f"{body.strip()} (Tier {int(c.tier)}, {TIER_NAME[c.tier]})."


def conflict_facts(
    instance: Instance,
    constraints: Mapping[str, Constraint],
    mus: Iterable[str],
    options: Iterable[OptionView] = (),
    ledger_counts: Mapping[str, float] | None = None,
) -> list[Fact]:
    facts: list[Fact] = []
    involved = [constraints[i] for i in mus]
    for c in involved:
        facts.append(Fact(c.id, describe(instance, c)))
        if c.source.rule:
            facts.append(Fact(f"RULE-{c.id}", f"This comes from the institute rule: {c.source.rule} [{c.id}]."))
    for eq in sorted({e for c in involved if c.room for e in c.room.equipment}):
        rooms = [r.name for r in instance.rooms if eq in r.equipment]
        facts.append(Fact(f"RES-{eq}", f"Rooms with {eq}: {', '.join(rooms) if rooms else 'none'}."))
    for o in options:
        where = "; ".join(f"{session_name(instance, s)} on {placement_text(instance, p)}"
                          for s, p in sorted(o.placements.items()))
        facts.append(Fact(f"OPT-{o.key}", f"Option {o.key}: {where}. The solver confirms this works."))
    owners = {c.owner for c in involved if c.owner in instance.faculty_by_id}
    for owner in sorted(owners):
        n = (ledger_counts or {}).get(owner, 0)
        if n:
            facts.append(Fact(f"LED-{owner}", f"{instance.faculty_by_id[owner].name} has conceded "
                                              f"{n:g} time{'s' if n != 1 else ''} before."))
    return facts


# ---------------------------------------------------------------------------
# Explanations and their checks
# ---------------------------------------------------------------------------


class Claim(BaseModel):
    text: str
    facts: list[str]


class ExplanationOut(BaseModel):
    claims: list[Claim]


class FreeExplanationOut(BaseModel):
    text: str


@dataclass
class Explanation:
    mode: str
    claims: list[tuple[str, list[str], bool]] = field(default_factory=list)  # (text, facts, supported)
    rejected: int = 0
    leaks: list[str] = field(default_factory=list)
    body: str | None = None  # the full text, when the model wrote free prose

    @property
    def text(self) -> str:
        return self.body if self.body is not None else " ".join(t for t, _, ok in self.claims if ok)

    @property
    def faithfulness(self) -> float:
        """Share of claims traceable to facts (H2a)."""
        anchored = [ok for _, _, ok in self.claims]
        return sum(anchored) / len(anchored) if anchored else 1.0


def _canon(text: str) -> str:
    return _CLOCK.sub(_clock, text)


class ClaimChecker:
    """A claim is supported when every day, number and name it mentions
    appears in the facts it cites."""

    def __init__(self, instance: Instance) -> None:
        self.check = FidelityCheck(instance)

    def anchors(self, text: str) -> tuple[set[str], set[str], set[str]]:
        t = _canon(text)
        return self.check.days(t), self.check.numbers(t), self.check.entities(t)

    def supported(self, text: str, cited: Iterable[Fact]) -> bool:
        cited = list(cited)
        if not cited:
            return False
        days, nums, ents = self.anchors(text)
        fd, fn, fe = set(), set(), set()
        for f in cited:
            d, n, e = self.anchors(f.text)
            fd |= d
            fn |= n
            fe |= e
        return days <= fd and nums <= fn and ents <= fe

    def traced(self, sentence: str, facts: Iterable[Fact]) -> bool | None:
        """For free text: ``None`` if the sentence mentions nothing checkable,
        else whether all its anchors appear somewhere in the facts."""
        days, nums, ents = self.anchors(sentence)
        if not (days or nums or ents):
            return None
        return self.supported(sentence, facts)


def leaks(text: str, private: Iterable[str] = ()) -> list[str]:
    low = text.lower()
    return [t for t in (*PRIVATE_TERMS, *(p.lower() for p in private)) if t and t in low]


GROUNDED_PROMPT = """You explain a timetabling conflict to one person and offer them options.
Write 3-6 short claims. Each claim cites the IDs of the facts it rests on;
use only those facts, and copy days, times, rooms and names exactly as the
facts give them. Be contrastive: say why the request as asked cannot work,
then what can. Mention the options by their letter. Never mention reasons
for anyone's unavailability. Address the recipient as "you"."""

FREE_PROMPT = """You explain a timetabling conflict to one person and offer them options.
Write a short, friendly message (3-6 sentences)."""


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


class Explainer:
    def __init__(self, instance: Instance, *, mode: str = "template", client=None) -> None:
        if mode not in ("template", "grounded", "free"):
            raise ValueError(mode)
        if mode != "template" and client is None:
            raise ValueError(f"{mode} explanations need an LLM client")
        self.instance = instance
        self.mode = mode
        self.client = client
        self.checker = ClaimChecker(instance)

    def template(self, facts: list[Fact], recipient: str | None = None) -> Explanation:
        out = Explanation(mode="template")
        conflict = [f for f in facts if not f.id.startswith(("OPT-", "LED-"))]
        if conflict:
            out.claims.append(("Your request cannot be met as asked, because these conflict:", [], True))
        for f in facts:
            out.claims.append((f.text, [f.id], True))
        return out

    def explain(self, facts: list[Fact], recipient: str | None = None, *,
                raw_requests: Iterable[str] = (), private: Iterable[str] = ()) -> Explanation:
        if self.mode == "template":
            out = self.template(facts, recipient)
        else:
            try:
                out = (self._grounded(facts, recipient) if self.mode == "grounded"
                       else self._free(facts, recipient, raw_requests))
            except LLMError:  # no usable output: send the template, and say so in the mode
                out = self.template(facts, recipient)
                out.mode = f"{self.mode}-failed"
        out.leaks = leaks(out.text, private)
        return out

    def _recipient(self, recipient: str | None) -> str:
        fac = self.instance.faculty_by_id.get(recipient or "")
        return fac.name if fac else (recipient or "the stakeholder")

    def grounded_prompt(self, facts: list[Fact], recipient: str | None) -> str:
        listing = "\n".join(f"[{f.id}] {f.text}" for f in facts)
        return f"Recipient: {self._recipient(recipient)}\n\n# Facts\n{listing}"

    def _grounded(self, facts: list[Fact], recipient: str | None) -> Explanation:
        by_id = {f.id: f for f in facts}
        got = self.client.generate(GROUNDED_PROMPT, self.grounded_prompt(facts, recipient), ExplanationOut)
        out = Explanation(mode="grounded")
        for c in got.claims:
            c.facts = [i.strip().strip("[]") for i in c.facts]  # small models copy the listing's brackets
            cited = [by_id[i] for i in c.facts if i in by_id]
            ok = len(cited) == len(c.facts) and self.checker.supported(c.text, cited)
            out.claims.append((c.text, c.facts, ok))
            out.rejected += not ok
        if not any(ok for _, _, ok in out.claims) or not any(
                ok and any(i.startswith("OPT-") for i in ids) for _, ids, ok in out.claims) and any(
                f.id.startswith("OPT-") for f in facts):
            fallback = self.template(facts, recipient)  # nothing usable, or the options got lost
            fallback.rejected = out.rejected
            fallback.mode = "grounded-fallback"
            return fallback
        return out

    def _free(self, facts: list[Fact], recipient: str | None, raw_requests: Iterable[str]) -> Explanation:
        options = "\n".join(f.text for f in facts if f.id.startswith("OPT-"))
        requests = "\n".join(f"- {r}" for r in raw_requests)
        prompt = (f"Recipient: {self._recipient(recipient)}\n\nRequests that clash:\n{requests}\n\n"
                  f"The timetable cannot satisfy all of them. Options:\n{options}")
        got = self.client.generate(FREE_PROMPT, prompt, FreeExplanationOut)
        out = Explanation(mode="free", body=got.text)
        for s in sentences(got.text):
            t = self.checker.traced(s, facts)
            if t is not None:
                out.claims.append((s, [], t))
        return out
