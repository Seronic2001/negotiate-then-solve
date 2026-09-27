"""System One decision model (proposal Section 8.2, step 1).

A small, fast, calibrated classifier over the request text: request type,
the next action (including refusal for missing authority), and a
confidence ``p``. Requests with ``p >= tau`` on a compilable type take the
fast path; everything else goes to the System Two LLM.

This is the proposal's fallback design (TF-IDF + logistic regression, the
"calibrated small classifier" in the risk table). SemIf, Kev or OpenJev
Verdict can replace it behind the same ``decide`` interface.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from core.schemas import Request

from .corpus import CorpusExample, ExpectedAction, RequestType

FAST_PATH_TYPES = frozenset({RequestType.PREFERENCE, RequestType.UNAVAILABILITY, RequestType.ROOM_ISSUE})


@dataclass
class Decision:
    request_type: RequestType
    type_p: float
    action: ExpectedAction
    action_p: float
    latency_ms: float

    @property
    def confidence(self) -> float:
        return min(self.type_p, self.action_p)

    def fast_path(self, tau: float) -> bool:
        return (
            self.request_type in FAST_PATH_TYPES
            and self.action == ExpectedAction.COMPILE
            and self.confidence >= tau
        )


def _features(request: Request) -> str:
    # The role is part of the input: the same words mean different things
    # from a student than from the faculty member who owns the class.
    return f"__role_{request.role.value}__ __channel_{request.channel.value}__ {request.raw_text}"


def _pipeline(c: float) -> Pipeline:
    return Pipeline([
        ("features", FeatureUnion([
            ("words", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, lowercase=True)),
            ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2)),
        ])),
        ("clf", LogisticRegression(C=c, max_iter=5000)),
    ])


class SystemOne:
    def __init__(self, c: float = 4.0) -> None:
        self.type_model = _pipeline(c)
        self.action_model = _pipeline(c)

    def fit(self, examples: Sequence[CorpusExample]) -> SystemOne:
        x = [_features(ex.request) for ex in examples]
        self.type_model.fit(x, [ex.request_type.value for ex in examples])
        self.action_model.fit(x, [ex.expected_action.value for ex in examples])
        return self

    def decide(self, request: Request) -> Decision:
        start = time.perf_counter()
        x = [_features(request)]
        tp = self.type_model.predict_proba(x)[0]
        ap = self.action_model.predict_proba(x)[0]
        ti, ai = int(np.argmax(tp)), int(np.argmax(ap))
        return Decision(
            request_type=RequestType(self.type_model.classes_[ti]),
            type_p=float(tp[ti]),
            action=ExpectedAction(self.action_model.classes_[ai]),
            action_p=float(ap[ai]),
            latency_ms=(time.perf_counter() - start) * 1000,
        )


def tune_tau(
    decisions: Sequence[Decision],
    examples: Sequence[CorpusExample],
    *,
    min_precision: float = 0.98,
    grid: Sequence[float] = tuple(np.round(np.arange(0.30, 1.0, 0.02), 2)),
) -> float:
    """Smallest threshold whose fast-path routes are right at least
    ``min_precision`` of the time on the validation set.

    Until the QLoRA compiler exists, "right" means System One's type and
    action are both correct; the proposal's criterion (compilation F1 within
    2 points of the LLM-only path) replaces this once it does.
    """
    for tau in sorted(grid):
        routed = [(d, ex) for d, ex in zip(decisions, examples, strict=True) if d.fast_path(tau)]
        if not routed:
            return tau
        correct = sum(d.request_type == ex.request_type and d.action == ex.expected_action for d, ex in routed)
        if correct / len(routed) >= min_precision:
            return tau
    return 1.0
