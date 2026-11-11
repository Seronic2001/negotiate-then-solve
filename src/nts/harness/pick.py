"""Which tools a request is offered: a question gets only the tools that read, everything else every tool.

    picker = ToolPicker.trained()
    harness = Harness(Registry(ALL_TOOLS), model, tracer, picker=picker)

System One (``language.system_one``, the linear SVM) reads the request. A question about the timetable or the
handbook, said with at least ``min_p`` confidence, is offered the read, rules, talk and end tools: about 2,300
tokens of schemas instead of about 6,000 for every tool, which leaves an 8k-context model room for the
conversation. 0.7: of 390 held-out change requests none scored over 0.6, and 47 of 70 held-out questions over 0.7. Anything else (any change, or a question it is unsure of) is offered every tool, since a change
offered too few tools could not be made, while a question offered too many only costs tokens.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nts.tools import Scope

DATA = Path(__file__).resolve().parents[3] / "data"

QUESTION_SCOPES = frozenset({Scope.READ, Scope.POLICY, Scope.TALK, Scope.END})
# words that ask for a change: a question with one of these ("when am I free? I want to take an extra class") is a
# change too, whatever System One says (it called that one a question, p 0.81, and the agent had no add_class)
CHANGE = re.compile(r"\b(?:extra|make[- ]?up|add|take|want|need|move|shift|swap|exchange|cancel|reschedul\w*|postpone|"
                    r"book|reserve|block|limit|away|leave|absent|unavailable|conference|can'?t|cannot|won'?t|instead|"
                    r"change|put|schedule|keep|go (?:on|to|at)|"
                    # a cap on the week ("Can my classes be packed into four days a week, at most?" read as a question)
                    r"at most|no more than|(?:never|not) (?:have |teach )?more than|pack(?:ed)?|fewer|cap)\b",
                    re.IGNORECASE)


@dataclass(frozen=True)
class Pick:
    scopes: frozenset[Scope] | None  # None: every scope the agent has
    request_type: str
    p: float


class ToolPicker:
    def __init__(self, system_one, *, min_p: float = 0.7) -> None:
        self.system_one = system_one
        self.min_p = min_p

    @classmethod
    def trained(cls, *, min_p: float = 0.7) -> ToolPicker:
        """System One trained as the web app trains it, with the questions as well."""
        from language.corpus import load_jsonl
        from language.system_one import SystemOne, intent_examples

        corpus = load_jsonl(DATA / "requests.jsonl") + load_jsonl(DATA / "requests-para.jsonl")
        train = [e for e in corpus if e.split == "train"] + intent_examples("train") + question_examples("train")
        return cls(SystemOne().fit(train), min_p=min_p)

    def __call__(self, request: str, teacher: bool) -> Pick:
        from core.schemas import Channel, Request, Role
        from language.corpus import ExpectedAction, RequestType

        d = self.system_one.decide(Request(id="pick", channel=Channel.PORTAL, sender_id="pick", raw_text=request,
                                           role=Role.FACULTY if teacher else Role.COORDINATOR,
                                           received_at=datetime(2026, 9, 1)))
        asked = (d.request_type in {getattr(RequestType, "QUESTION", RequestType.POLICY_QUESTION), RequestType.POLICY_QUESTION}
                 and d.action == ExpectedAction.ANSWER and d.confidence >= self.min_p and not CHANGE.search(request))
        return Pick(QUESTION_SCOPES if asked else None, d.request_type.value, round(d.confidence, 3))


def question_examples(split: str) -> list:
    """Questions, answered by reading: the timetable ones of ``data/questions.jsonl`` (type ``question``) and the
    handbook questions of ``data/retrieval-queries.jsonl`` (type ``policy_question``; odd lines train, even test)."""
    from core.schemas import Channel, Request, Role
    from language.corpus import ExpectedAction, RequestType
    from language.system_one import Labelled

    def asked(text: str, rtype, kind: str, n: int):
        r = Request(id=f"Q-{n}", channel=Channel.PORTAL, sender_id="F-0", role=Role.FACULTY, raw_text=text,
                    received_at=datetime(2026, 9, 1))
        return Labelled(r, rtype, ExpectedAction.ANSWER, kind, split)

    rows = [json.loads(line) for line in (DATA / "questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    qtype = getattr(RequestType, "QUESTION", RequestType.POLICY_QUESTION)  # the demo corpus has no type of its own for these
    out = [asked(r["text"], qtype, "question", n) for n, r in enumerate(rows) if r["split"] == split]
    handbook = [json.loads(line)["query"] for line in
                (DATA / "retrieval-queries.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    want = {"train": 0, "test": 1}.get(split)
    return out + [asked(q, RequestType.POLICY_QUESTION, "policy_question", n) for n, q in enumerate(handbook) if n % 2 == want]
