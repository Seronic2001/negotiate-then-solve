"""Statistics for the evaluation protocol (proposal Section 12.5): 95%
bootstrap confidence intervals, McNemar's test for paired pass/fail
outcomes, Wilcoxon signed-rank for paired continuous outcomes, and Cohen's
kappa for validating the LLM judge against human annotators."""

from __future__ import annotations

import random
from collections.abc import Sequence

from scipy import stats as _st


def mean(xs: Sequence[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def bootstrap_ci(xs: Sequence[float], n: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float] | None:
    xs = [float(x) for x in xs if x is not None]
    if not xs:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(xs, k=len(xs))) / len(xs) for _ in range(n))
    return means[int(n * alpha / 2)], means[int(n * (1 - alpha / 2)) - 1]


def mcnemar(a: Sequence[bool], b: Sequence[bool]) -> dict:
    """Exact McNemar test on paired booleans (same scenarios, two systems)."""
    only_a = sum(x and not y for x, y in zip(a, b, strict=True))
    only_b = sum(y and not x for x, y in zip(a, b, strict=True))
    n = only_a + only_b
    p = 1.0 if n == 0 else _st.binomtest(only_a, n, 0.5).pvalue
    return {"only_first": only_a, "only_second": only_b, "p": p}


def wilcoxon(a: Sequence[float], b: Sequence[float]) -> dict:
    pairs = [(x, y) for x, y in zip(a, b, strict=True) if x is not None and y is not None]
    diffs = [x - y for x, y in pairs]
    if not diffs or all(d == 0 for d in diffs):
        return {"n": len(diffs), "p": 1.0, "median_diff": 0.0}
    res = _st.wilcoxon([x for x, _ in pairs], [y for _, y in pairs], zero_method="zsplit")
    diffs.sort()
    return {"n": len(diffs), "p": float(res.pvalue), "median_diff": diffs[len(diffs) // 2]}


def cohen_kappa(a: Sequence, b: Sequence, weights: str | None = None) -> float:
    """``weights="quadratic"`` for ordinal ratings such as Likert scores."""
    from sklearn.metrics import cohen_kappa_score

    return float(cohen_kappa_score(list(a), list(b), weights=weights))
