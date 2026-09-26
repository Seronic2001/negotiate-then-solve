"""Concession ledger and fairness measures (proposal Sections 8.6 and 12).

Every accepted concession adds credit to the stakeholder who conceded.
Credit lowers the chance of being asked to concede again, and it decays each
semester so history matters without dominating. The concession Gini
coefficient across stakeholders is the fairness metric of H1d.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping

from .schemas import ConcessionEntry


def gini(values: Iterable[float]) -> float:
    """Gini coefficient of non-negative values: 0 is perfectly even, values
    near 1 mean one stakeholder carries everything. All zeros give 0."""
    xs = sorted(max(0.0, float(v)) for v in values)
    n, total = len(xs), sum(xs)
    if n == 0 or total == 0:
        return 0.0
    weighted = sum((i + 1) * x for i, x in enumerate(xs))
    return (2 * weighted) / (n * total) - (n + 1) / n


class ConcessionLedger:
    def __init__(self, entries: Iterable[ConcessionEntry] = (), *, decay: float = 0.5) -> None:
        self.entries: list[ConcessionEntry] = list(entries)
        self.decay = decay

    def record(self, entry: ConcessionEntry) -> None:
        self.entries.append(entry)

    def semesters(self) -> list[str]:
        """Semester labels sort chronologically ("2025-2" < "2026-1")."""
        return sorted({e.semester for e in self.entries})

    def credit(self, stakeholder: str, semester: str) -> float:
        """Decayed credit as of ``semester``: this semester counts fully, the
        previous one ``decay`` times, and so on. Later semesters are ignored."""
        order = sorted({e.semester for e in self.entries} | {semester})
        now = order.index(semester)
        total = 0.0
        for e in self.entries:
            if e.stakeholder != stakeholder:
                continue
            age = now - order.index(e.semester)
            if age >= 0:
                total += e.credit * self.decay**age
        return total

    def credits(self, stakeholders: Iterable[str], semester: str) -> dict[str, float]:
        return {s: self.credit(s, semester) for s in stakeholders}

    def counts(self, semester: str | None = None) -> dict[str, float]:
        """Undecayed concessions per stakeholder, optionally in one semester."""
        out: dict[str, float] = defaultdict(float)
        for e in self.entries:
            if semester is None or e.semester == semester:
                out[e.stakeholder] += e.credit
        return dict(out)

    def gini(self, stakeholders: Iterable[str], semester: str | None = None) -> float:
        counts = self.counts(semester)
        return gini(counts.get(s, 0.0) for s in stakeholders)

    def delta_gini(self, stakeholders: Iterable[str], conceders: Mapping[str, float],
                   semester: str | None = None) -> float:
        """How much the Gini would change if ``conceders`` conceded now."""
        people = list(stakeholders)
        counts = self.counts(semester)
        before = gini(counts.get(s, 0.0) for s in people)
        after = gini(counts.get(s, 0.0) + conceders.get(s, 0.0) for s in people)
        return after - before
