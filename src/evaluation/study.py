"""Human data (proposal Section 12.5): judge validation by the team and the
anonymised faculty pilot, collected in the web app (``/study``).

    uv run python -m evaluation.study build runs/negotiation-study-source.json   # the item sets
    uv run python -m evaluation.study report                                     # kappas, H3, live checks

Three labelling tasks are built from one negotiation report (``ours-llm`` and
``A2`` with ``explanations`` recorded, seed 0):

* ``claims``   100 explanation claims with the facts the explanation could use;
               the label is "supported by the facts or not". Machine label:
               the faithfulness verifier. Every claim the verifier rejected is
               kept (up to 40), the rest are sampled, half grounded, half free.
* ``replies``  100 stakeholder replies under the message they answer; the label
               is what the reply does (accept an option, counter, decline,
               other). Machine label: the recorded reply call.
* ``ratings``  110 messages rated 1-5 for clarity and acceptability, blind to the
               configuration. Grounded (ours-llm) and free-form (A2) messages
               come in pairs from the same scenario; a 24-message subset is the
               pilot set (H3: "the human pilot rates clarity and acceptability");
               unpaired grounded messages fill the set to 110 for the judge kappa.

Team raters (codes ``T-n``) do all three; pilot participants (``P-nn``) rate
the pilot set and take part in a live session in the portal as one demo
faculty member: they write a request in their own words, say whether the
system understood it, reply to the negotiator in their own words, confirm the
reading of the reply, and rate the message they received.

Nothing identifies a participant beyond the code. Everything is stored under
``runs/study/`` (``participants.json``, ``labels.jsonl``, ``live.jsonl``);
``report`` writes ``human_ratings.csv`` in the format ``evaluation.judge --kappa``
reads. LLM-scored metrics are reported only where kappa >= 0.6 (Section 12.5).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import threading
from collections import Counter, defaultdict
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

from .stats import cohen_kappa, mean, wilcoxon

TASKS = ("claims", "replies", "ratings")
GROUNDED, FREE = "ours-llm", "A2"
N_CLAIMS, N_REPLIES, N_RATINGS, MAX_UNSUPPORTED, PILOT_PAIRS = 100, 100, 110, 40, 12
KAPPA_OK = 0.6
REPLY_LABELS = ("accept:A", "accept:B", "accept:C", "counter", "reject", "other")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def judge_id(config: str, scenario: str, k: int, seed: int = 0) -> str:
    """The message id ``evaluation.judge`` uses, so human and judge ratings join."""
    return f"{config}/{scenario}/{k + 1}" if not seed else f"{config}/{scenario}/s{seed}/{k + 1}"


def reply_label(reply: dict) -> str:
    d = reply.get("decision")
    if d == "accept":
        return f"accept:{(reply.get('choice') or '').strip().upper()}"
    return d if d in ("counter", "reject") else "other"


# ---------------------------------------------------------------------------
# Item sets
# ---------------------------------------------------------------------------


def build_items(report: dict, seed: int = 0, rng_seed: int = 0) -> dict:
    rng = random.Random(rng_seed)
    rows = {c: [r for r in report["configs"][c]["rows"] if r.get("seed", 0) == seed] for c in (GROUNDED, FREE)}
    if any("explanations" not in r for rs in rows.values() for r in rs):
        raise SystemExit("the report has no recorded explanations: re-run evaluation.negotiation (it records them now)")

    claims = []
    for config, rs in rows.items():
        for r in rs:
            for k, e in enumerate(r["explanations"]):
                for j, c in enumerate(e["claims"]):
                    claims.append({"config": config, "mode": e["mode"], "scenario": r["scenario"], "message": k,
                                   "claim": c["text"], "cited": c["facts"], "facts": e["facts"],
                                   "machine": bool(c["supported"]), "key": f"{config}/{r['scenario']}/{k}/{j}"})
    unsupported = [c for c in claims if not c["machine"]]
    picked = rng.sample(unsupported, min(MAX_UNSUPPORTED, len(unsupported)))
    for mode in ("grounded", "free"):
        pool = [c for c in claims if c["machine"] and c["mode"] == mode]
        picked += rng.sample(pool, min(len(pool), (N_CLAIMS - len(picked)) // (2 if mode == "grounded" else 1)))
    rng.shuffle(picked)
    claims = [{"id": f"CL-{i + 1:03d}", **c} for i, c in enumerate(picked)]

    replies = []
    for config, rs in rows.items():
        for r in rs:
            for k, (text, rep) in enumerate(zip(r["messages"], r["replies"], strict=False)):
                if rep.get("text") and rep.get("decision") != "no_reply":
                    replies.append({"config": config, "scenario": r["scenario"], "message": text,
                                    "reply": rep["text"], "machine": reply_label(rep), "key": f"{config}/{r['scenario']}/{k}"})
    by_label = defaultdict(list)
    for x in replies:
        by_label[x["machine"]].append(x)
    picked = []
    while len(picked) < min(N_REPLIES, len(replies)):  # round-robin over labels: rare ones are all kept
        for xs in by_label.values():
            if xs and len(picked) < N_REPLIES:
                picked.append(xs.pop(rng.randrange(len(xs))))
    rng.shuffle(picked)
    replies = [{"id": f"RE-{i + 1:03d}", **x} for i, x in enumerate(picked)]

    msgs = {c: {(r["scenario"], k): m for r in rs for k, m in enumerate(r["messages"])} for c, rs in rows.items()}
    paired = sorted(set(msgs[GROUNDED]) & set(msgs[FREE]))
    ratings = []
    for config in (GROUNDED, FREE):
        for sc, k in paired:
            ratings.append({"id": judge_id(config, sc, k, seed), "config": config,
                            "mode": "grounded" if config == GROUNDED else "free", "scenario": sc, "message": k,
                            "text": msgs[config][(sc, k)], "pilot": False})
    extra = [p for p in sorted(msgs[GROUNDED]) if p not in set(paired)]
    for sc, k in rng.sample(extra, min(len(extra), max(0, N_RATINGS - len(ratings)))):  # judge kappa needs >= 100
        ratings.append({"id": judge_id(GROUNDED, sc, k, seed), "config": GROUNDED, "mode": "grounded",
                        "scenario": sc, "message": k, "text": msgs[GROUNDED][(sc, k)], "pilot": False})
    firsts = [p for p in paired if p[1] == 0]
    kinds = defaultdict(list)
    for p in firsts:
        kinds[p[0].split("-", 2)[-1]].append(p)
    pilot: list[tuple[str, int]] = []
    while len(pilot) < min(PILOT_PAIRS, len(firsts)):  # spread over conflict kinds
        for xs in kinds.values():
            if xs and len(pilot) < PILOT_PAIRS:
                pilot.append(xs.pop(0))
    for it in ratings:
        it["pilot"] = (it["scenario"], it["message"]) in pilot
    return {"built": _now(), "seed": seed, "claims": claims, "replies": replies, "ratings": ratings}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class Study:
    """Participants, labels and live-session records under one directory."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # -- items ----------------------------------------------------------------------------

    @property
    def items_path(self) -> Path:
        return self.root / "items.json"

    def items(self) -> dict | None:
        return json.loads(self.items_path.read_text(encoding="utf-8")) if self.items_path.exists() else None

    def save_items(self, items: dict) -> None:
        self.items_path.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")

    def tasks_for(self, kind: str) -> list[str]:
        return list(TASKS) if kind == "team" else ["ratings"]

    def queue(self, code: str, kind: str, task: str) -> list[dict]:
        """The rater's items for a task, in an order of their own (blind to configuration)."""
        items = (self.items() or {}).get(task, [])
        if task == "ratings" and kind == "pilot":
            items = [i for i in items if i["pilot"]]
        seed = int(hashlib.sha256(f"{code}/{task}".encode()).hexdigest()[:8], 16)
        items = list(items)
        random.Random(seed).shuffle(items)
        return items

    # -- participants ---------------------------------------------------------------------

    @property
    def participants_path(self) -> Path:
        return self.root / "participants.json"

    def participants(self) -> dict[str, dict]:
        p = self.participants_path
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def _save_participants(self, ps: dict) -> None:
        self.participants_path.write_text(json.dumps(ps, indent=1), encoding="utf-8")

    def add_participants(self, kind: str, n: int, persona: str | None = None) -> list[str]:
        if kind not in ("team", "pilot"):
            raise ValueError("kind must be team or pilot")
        with self._lock:
            ps = self.participants()
            prefix = "T-" if kind == "team" else "P-"
            taken = [int(c[2:]) for c in ps if c.startswith(prefix)]
            start = max(taken, default=0) + 1
            codes = [f"{prefix}{i}" if kind == "team" else f"{prefix}{i:02d}" for i in range(start, start + n)]
            for c in codes:
                ps[c] = {"kind": kind, "persona": persona if kind == "pilot" else None, "created": _now(),
                         "consented": None}
            self._save_participants(ps)
        return codes

    def get(self, code: str) -> dict | None:
        p = self.participants().get(code.strip().upper())
        return p and {"code": code.strip().upper(), **p}

    def consent(self, code: str) -> dict:
        with self._lock:
            ps = self.participants()
            ps[code]["consented"] = ps[code]["consented"] or _now()
            self._save_participants(ps)
        return {"code": code, **ps[code]}

    # -- labels and live records -----------------------------------------------------------

    def _append(self, name: str, row: dict) -> dict:
        row = {"at": _now(), **row}
        with self._lock, (self.root / name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def _read(self, name: str) -> list[dict]:
        p = self.root / name
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x] if p.exists() else []

    def label(self, code: str, task: str, item: str, value: dict) -> dict:
        return self._append("labels.jsonl", {"code": code, "task": task, "item": item, "value": value})

    def labels(self) -> dict[tuple[str, str], dict[str, dict]]:
        """{(task, code): {item: value}}, the latest label of each item."""
        out: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
        for r in self._read("labels.jsonl"):
            out[(r["task"], r["code"])][r["item"]] = r["value"]
        return out

    def live(self, code: str, persona: str, kind: str, **fields) -> dict:
        return self._append("live.jsonl", {"code": code, "persona": persona, "kind": kind, **fields})

    def live_rows(self) -> list[dict]:
        return self._read("live.jsonl")

    def progress(self, code: str, kind: str) -> dict[str, dict]:
        labels = self.labels()
        out = {}
        for task in self.tasks_for(kind):
            q = self.queue(code, kind, task)
            done = labels.get((task, code), {})
            out[task] = {"done": sum(i["id"] in done for i in q), "total": len(q)}
        return out


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _kappa(a: list, b: list, weights: str | None = None) -> float | None:
    if len(a) < 2:
        return None
    k = cohen_kappa(a, b, weights=weights)
    return None if math.isnan(k) else round(k, 3)


def _pairwise(by_rater: dict[str, dict[str, object]], weights: str | None = None) -> dict:
    out = {}
    for a, b in combinations(sorted(by_rater), 2):
        common = sorted(set(by_rater[a]) & set(by_rater[b]))
        if len(common) >= 2:
            out[f"{a} vs {b}"] = {"n": len(common),
                                  "kappa": _kappa([by_rater[a][i] for i in common], [by_rater[b][i] for i in common],
                                                  weights)}
    return out


def _vs_machine(by_rater: dict[str, dict[str, object]], machine: dict[str, object]) -> dict:
    out = {}
    for r, labels in sorted(by_rater.items()):
        common = sorted(set(labels) & set(machine))
        if common:
            h, m = [labels[i] for i in common], [machine[i] for i in common]
            k = _kappa(h, m)
            out[r] = {"n": len(common), "kappa": k, "agreement": round(mean([x == y for x, y in zip(h, m, strict=True)]), 3),
                      "ok": k is not None and k >= KAPPA_OK}
    return out


def analyse(study: Study, judge_ratings: dict[str, dict] | None = None) -> dict:
    items = study.items() or {t: [] for t in TASKS}
    ps = study.participants()
    labels = study.labels()
    team = {c for c, p in ps.items() if p["kind"] == "team"}
    pilot = {c for c, p in ps.items() if p["kind"] == "pilot"}

    def rater_labels(task: str, codes: set[str], field: str) -> dict[str, dict[str, object]]:
        return {c: {i: v[field] for i, v in labels.get((task, c), {}).items() if field in v}
                for c in codes if labels.get((task, c))}

    claim_h = rater_labels("claims", team, "supported")
    reply_h = rater_labels("replies", team, "label")
    report: dict = {
        "participants": {"team": len(team), "pilot": len(pilot),
                         "pilot_consented": sum(bool(ps[c]["consented"]) for c in pilot)},
        "claims": {"items": len(items["claims"]),
                   "human_vs_verifier": _vs_machine(claim_h, {i["id"]: i["machine"] for i in items["claims"]}),
                   "human_vs_human": _pairwise(claim_h)},
        "replies": {"items": len(items["replies"]),
                    "human_vs_recorded": _vs_machine(reply_h, {i["id"]: i["machine"] for i in items["replies"]}),
                    "human_vs_human": _pairwise(reply_h)},
    }

    rating_rows = []  # (code, kind, item, clarity, acceptability)
    for (task, code), vals in labels.items():
        if task == "ratings" and code in ps:
            rating_rows += [(code, ps[code]["kind"], i, v["clarity"], v["acceptability"]) for i, v in vals.items()]
    by_rater = defaultdict(dict)
    for code, kind, i, c, a in rating_rows:
        if kind == "team":
            by_rater[code][i] = (c, a)
    if judge_ratings:
        by_rater["llm_judge"] = {i: (v["clarity"], v["acceptability"]) for i, v in judge_ratings.items()}
    kappas = {}
    for k, idx in (("clarity", 0), ("acceptability", 1)):
        for pair, v in _pairwise({r: {i: x[idx] for i, x in d.items()} for r, d in by_rater.items()}, "quadratic").items():
            kappas.setdefault(pair, {"n": v["n"]})[k] = v["kappa"]
    meta = {i["id"]: i for i in items["ratings"]}
    report["ratings"] = {"items": len(items["ratings"]), "pilot_items": sum(i["pilot"] for i in items["ratings"]),
                         "kappa": kappas, "h3_pilot": _h3(rating_rows, meta, "pilot"),
                         "h3_team": _h3(rating_rows, meta, "team")}

    live = study.live_rows()
    understood = Counter(r["value"] for r in live if r["kind"] == "understood")
    reply_checks = [r for r in live if r["kind"] == "reply"]
    live_ratings = [r for r in live if r["kind"] == "rating"]
    report["live"] = {
        "requests_checked": sum(understood.values()), "understood": dict(understood),
        "replies": len(reply_checks),
        "reply_reading_confirmed": mean([r["confirmed"] for r in reply_checks]),
        "message_ratings": len(live_ratings),
        "clarity": mean([r["value"]["clarity"] for r in live_ratings]),
        "acceptability": mean([r["value"]["acceptability"] for r in live_ratings]),
    }
    return report


def _h3(rows: list[tuple], meta: dict[str, dict], kind: str) -> dict:
    """Grounded vs free-form ratings from one group of raters, paired on
    (rater, scenario, message)."""
    by = defaultdict(dict)
    for code, k, i, c, a in rows:
        if k == kind and i in meta:
            m = meta[i]
            by[(code, m["scenario"], m["message"])][m["mode"]] = (c, a)
    pairs = [v for v in by.values() if "grounded" in v and "free" in v]
    out: dict = {"raters": len({code for code, k, *_ in rows if k == kind}), "pairs": len(pairs)}
    for name, idx in (("clarity", 0), ("acceptability", 1)):
        g = [p["grounded"][idx] for p in pairs]
        f = [p["free"][idx] for p in pairs]
        out[name] = {"grounded": mean(g), "free": mean(f), "wilcoxon": wilcoxon(g, f) if pairs else None}
    return out


def write_ratings_csv(study: Study, path: Path) -> int:
    """Team ratings in the ``evaluation.judge --kappa`` format."""
    ps = study.participants()
    rows = [(i, code, v["clarity"], v["acceptability"]) for (task, code), vals in study.labels().items()
            if task == "ratings" and ps.get(code, {}).get("kind") == "team" for i, v in vals.items()]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["message_id", "rater", "clarity", "acceptability"])
        w.writerows(sorted(rows))
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the item sets from a negotiation report")
    b.add_argument("report", type=Path)
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--force", action="store_true", help="replace items that already have labels")
    r = sub.add_parser("report", help="kappas, H3 and the live checks")
    r.add_argument("--judge", type=Path, default=Path("runs/judge-ratings.json"))
    for p in (b, r):
        p.add_argument("--dir", type=Path, default=Path("runs/study"))
    args = ap.parse_args()
    study = Study(args.dir)
    if args.cmd == "build":
        if study.items() and study.labels() and not args.force:
            raise SystemExit("labels exist for the current items; pass --force to rebuild (labels would no longer match)")
        items = build_items(json.loads(args.report.read_text(encoding="utf-8")), seed=args.seed)
        items["source"] = str(args.report)
        study.save_items(items)
        print(f"{len(items['claims'])} claims, {len(items['replies'])} replies, {len(items['ratings'])} messages "
              f"({sum(i['pilot'] for i in items['ratings'])} in the pilot set) -> {study.items_path}")
        print("claims by verifier label:", dict(Counter(i["machine"] for i in items["claims"])),
              "| replies by label:", dict(Counter(i["machine"] for i in items["replies"])))
    else:
        judge = json.loads(args.judge.read_text(encoding="utf-8")) if args.judge.exists() else None
        print(json.dumps(analyse(study, judge), indent=1))
        n = write_ratings_csv(study, study.root / "human_ratings.csv")
        print(f"{n} team ratings -> {study.root / 'human_ratings.csv'} (evaluation.judge --kappa)")


if __name__ == "__main__":
    main()
