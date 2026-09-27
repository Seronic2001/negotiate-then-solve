"""Safety set construction and the judge's plumbing (no API calls)."""

import csv

from evaluation.benchmark import build
from evaluation.judge import _Rating, _Ratings, judge, kappa_report
from evaluation.safety import CompromisedParser, evaluate, make_cases
from evaluation.stats import bootstrap_ci, cohen_kappa, mcnemar, wilcoxon
from pipeline.ingest import Directory


def test_safety_set_has_fifty_cases_in_every_category():
    sc = build("contention", 1, seed=5)
    cases = make_cases(sc.instance, Directory.from_instance(sc.instance))
    assert len(cases) == 50 and len({c.id for c in cases}) == 50
    cats = {c.category for c in cases}
    assert cats == {"authority_student", "authority_colleague", "authority_claim", "approval_by_text",
                    "injection_with_request", "injection_only", "privacy", "spoofing"}


def test_deterministic_defences_hold_against_a_compromised_parser():
    report = evaluate(lambda inst: CompromisedParser(inst, "F-301"))
    assert report["unapproved_publishes"] == 0
    assert report["authority_violations"] == 0
    assert report["private_leaks"] == 0
    assert report["injection_successes"] == 0


class StubJudge:
    def generate(self, system, prompt, schema, **_):
        ids = [line.split('"')[1] for line in prompt.splitlines() if line.startswith("<message id=")]
        return _Ratings(ratings=[_Rating(id=i, clarity=4, acceptability=5) for i in ids])


def test_judge_batches_and_kappa(tmp_path):
    msgs = [{"id": f"m{i}", "config": "ours", "text": f"message {i}"} for i in range(23)]
    ratings = judge(msgs, StubJudge(), batch=10)
    assert len(ratings) == 23 and ratings["m0"] == {"clarity": 4, "acceptability": 5}
    path = tmp_path / "human.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["message_id", "rater", "clarity", "acceptability"])
        for i in range(23):
            w.writerow([f"m{i}", "h1", 3 + i % 3, 4 + i % 2])
            w.writerow([f"m{i}", "h2", 3 + i % 3, 4 + (i + 1) % 2])
    report = kappa_report(path, ratings)
    assert report["h1 vs h2"]["clarity"] == 1.0 and report["h1 vs h2"]["n"] == 23
    assert "h1 vs llm_judge" in report


def test_stats():
    assert mcnemar([True] * 10, [False] * 10)["p"] < 0.01
    assert mcnemar([True, False], [True, False])["p"] == 1.0
    lo, hi = bootstrap_ci([1, 2, 3, 4, 5])
    assert lo < 3 < hi
    assert wilcoxon([1, 2, 3], [1, 2, 3])["p"] == 1.0
    assert cohen_kappa([1, 2, 3], [1, 2, 3]) == 1.0
