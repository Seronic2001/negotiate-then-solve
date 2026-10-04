"""Plain words for the people using the service. The pipeline states tiers
("(Tier 4, operational requirement)", "a Tier 0-2 change") because the
solver, the explainer's facts and the model prompts depend on that exact text;
the web views translate it on the way out, so nothing upstream (or any cached
model answer) changes."""

from __future__ import annotations

import re

# what each tier means to the person reading, and who could ever change it
TIER_LABEL = {0: "Can't be changed", 1: "Institute rule", 2: "Agreed commitment", 3: "Confirmed absence",
              4: "Teaching need", 5: "Preference"}
TIER_WHO = {0: "Nobody, it is physically impossible otherwise",
            1: "Only the Dean or the academic council can make an exception",
            2: "Only the academic office can change it",
            3: "Kept, unless the person offers an alternative themselves",
            4: "The owner or the head of department can agree to change it",
            5: "Kept where possible; the owner can give it up freely"}

_TIER_NOTE = re.compile(r"\s*\(Tier (\d), [^)]*\)")
_PHRASES = {
    "every option needs a Tier 0-2 change":
        "every way to fit this in would break something fixed, an institute rule or an agreed commitment, "
        "so a person with the authority has to decide",
}


def plain(text: str | None) -> str | None:
    """"Lab 3 is unavailable in week 9 (Tier 0, physical)." -> "... (can't be changed)."""
    if not text:
        return text
    text = _TIER_NOTE.sub(lambda m: f" ({TIER_LABEL[int(m[1])].lower()})", text)
    for old, new in _PHRASES.items():
        text = text.replace(old, new)
    return text
