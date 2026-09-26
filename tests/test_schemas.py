import json
import re
from datetime import datetime

import pytest
from pydantic import ValidationError

from nts.schemas import Constraint, Request, RequestStatus, Tier

# The constraint record from proposal Section 7.4, comments included.
PROPOSAL_EXAMPLE = """
{ "id": "C-0412",
  "type": "unavailable",           // unavailable | prefer | avoid | require_room
  "hard": true,  "tier": 3,        // T0..T5 (Section 8.3)
  "owner": "F-102",                // Dr. Menon
  "scope": {"faculty": "F-102"},
  "when": {"days": ["Tue","Wed","Thu"], "weeks": [7]},
  "justification": "verified",     // none | stated | verified (kept private)
  "source": {"request": "R-2291", "rule": null},
  "valid": {"from_week": 7, "to_week": 7},
  "weight": null }
"""


def test_proposal_example_parses():
    c = Constraint.model_validate(json.loads(re.sub(r"//[^\n]*", "", PROPOSAL_EXAMPLE)))
    assert c.tier == Tier.VERIFIED_UNAVAILABILITY
    assert c.scope.faculty == "F-102"
    assert not c.active_in(None)  # not part of the semester-wide timetable
    assert c.active_in(7)
    assert not c.active_in(8)


@pytest.mark.parametrize(
    "fields",
    [
        {"type": "prefer", "hard": False, "tier": 0},  # Tier 0 must be hard
        {"type": "prefer", "hard": True, "tier": 5},  # Tier 5 must be soft
        {"type": "unavailable", "hard": False, "tier": 3},  # unavailability is always hard
        {"type": "require_room", "hard": True, "tier": 4},  # needs a room requirement
        {"type": "prefer", "hard": True, "tier": 3, "scope": {"faculty": "F-1", "group": "G-1"}},
    ],
)
def test_inconsistent_constraints_rejected(fields):
    with pytest.raises(ValidationError):
        Constraint.model_validate({"id": "C-1", **fields})


def test_request_lifecycle_rejects_skipping_approval():
    r = Request(id="R-1", channel="email", sender_id="F-102", role="faculty",
                raw_text="...", received_at=datetime(2026, 9, 1))
    for status in ("classified", "policy_checked", "compiled", "solved", "fairness_audited", "awaiting_approval"):
        r.advance(RequestStatus(status))
    r.advance(RequestStatus.PUBLISHED)

    r2 = Request(id="R-2", channel="email", sender_id="F-102", role="faculty",
                 raw_text="...", received_at=datetime(2026, 9, 1), status=RequestStatus.SOLVED)
    with pytest.raises(ValueError):
        r2.advance(RequestStatus.PUBLISHED)
