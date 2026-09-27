"""LLM judge for negotiation messages, and its validation against humans
(proposal Section 12.5).

    uv run python -m evaluation.judge runs/negotiation-XXXX.json            # rate messages (Flash-Lite, batched)
    uv run python -m evaluation.judge --kappa data/human_ratings.csv        # judge vs humans, human vs human

The judge rates each message 1-5 for clarity and for acceptability (would
the recipient find the request reasonable). Messages are rated in batches of
10 per call: this is offline bulk scoring, and every message is judged on
its own text.

``human_ratings.csv`` columns: ``message_id,rater,clarity,acceptability``,
with at least two human raters on at least 100 messages. The report gives
quadratic-weighted Cohen's kappa for each pair.
"""

from __future__ import annotations

import argparse
import csv
import json
from itertools import combinations
from pathlib import Path

from pydantic import BaseModel, Field

from language.llm import GeminiClient, default_model

from .stats import mean

JUDGE_PROMPT = """You rate messages that a university timetabling system sent to faculty
members to resolve scheduling conflicts. For each message give two scores:
clarity (1 = confusing, 5 = immediately clear what happened and what to do)
and acceptability (1 = the recipient would find it unreasonable or rude,
5 = fair, respectful and easy to agree to). Judge each message on its own."""


class _Rating(BaseModel):
    id: str
    clarity: int = Field(ge=1, le=5)
    acceptability: int = Field(ge=1, le=5)


class _Ratings(BaseModel):
    ratings: list[_Rating]


def messages_from_report(path: Path) -> list[dict]:
    report = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for config, block in report["configs"].items():
        for row in block["rows"]:
            for k, text in enumerate(row.get("messages", [])):
                out.append({"id": f"{config}/{row['scenario']}/{k + 1}", "config": config, "text": text})
    return out


def judge(messages: list[dict], client, batch: int = 10) -> dict[str, dict]:
    ratings: dict[str, dict] = {}
    for i in range(0, len(messages), batch):
        chunk = messages[i : i + batch]
        prompt = "\n\n".join(f'<message id="{m["id"]}">\n{m["text"]}\n</message>' for m in chunk)
        got = client.generate(JUDGE_PROMPT, prompt, _Ratings)
        for r in got.ratings:
            ratings[r.id] = {"clarity": r.clarity, "acceptability": r.acceptability}
    return ratings


def kappa_report(path: Path, judge_ratings: dict[str, dict] | None = None) -> dict:
    from sklearn.metrics import cohen_kappa_score

    by_rater: dict[str, dict[str, dict]] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_rater.setdefault(row["rater"], {})[row["message_id"]] = {
                "clarity": int(row["clarity"]), "acceptability": int(row["acceptability"])}
    if judge_ratings:
        by_rater["llm_judge"] = judge_ratings
    out = {}
    for a, b in combinations(sorted(by_rater), 2):
        common = sorted(set(by_rater[a]) & set(by_rater[b]))
        if len(common) < 2:
            continue
        out[f"{a} vs {b}"] = {"n": len(common), **{
            k: float(cohen_kappa_score([by_rater[a][m][k] for m in common], [by_rater[b][m][k] for m in common],
                                       weights="quadratic")) for k in ("clarity", "acceptability")}}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", type=Path, nargs="?", help="a negotiation report from evaluation.negotiation")
    ap.add_argument("--kappa", type=Path, default=None, help="human ratings CSV")
    ap.add_argument("--ratings", type=Path, default=Path("runs/judge-ratings.json"))
    args = ap.parse_args()
    ratings = json.loads(args.ratings.read_text(encoding="utf-8")) if args.ratings.exists() else {}
    if args.report:
        msgs = messages_from_report(args.report)
        todo = [m for m in msgs if m["id"] not in ratings]
        if todo:
            ratings |= judge(todo, GeminiClient(default_model("simulator")))
            args.ratings.write_text(json.dumps(ratings, indent=1), encoding="utf-8")
        by_config: dict[str, list[dict]] = {}
        for m in msgs:
            if m["id"] in ratings:
                by_config.setdefault(m["config"], []).append(ratings[m["id"]])
        print(json.dumps({c: {"n": len(v), "clarity": mean([r["clarity"] for r in v]),
                              "acceptability": mean([r["acceptability"] for r in v])}
                          for c, v in by_config.items()}, indent=1))
    if args.kappa:
        print(json.dumps(kappa_report(args.kappa, ratings), indent=1))


if __name__ == "__main__":
    main()
