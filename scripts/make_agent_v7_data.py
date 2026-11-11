"""The agent-v7 training data: agent-v6's rows and the v7 families' episodes, mixed by the Phase 2 rules
(docs/improvement-plan.md, items 6-8):

    python scripts/make_agent_v7_data.py ../negotiate-then-solve-agentic/data/agent-v6 data/agent-v7-new data/agent-v7

* every teacher-model (Gemini) episode of both, train and val as each export split them (by request text);
* the agent's own earlier runs (served+nts-agent-*) at most 20% of the training episodes (v6: 280 of 772, 36%),
  kept first for the families the teacher episodes cover least, so no family loses its only rows;
* a floor of 25 training episodes per family: a family below it is topped up with copies of its own episodes
  (upsampling the newest and thinnest kinds instead of another epoch);
* DPO pairs from both, outcome and fix (a fix pair without a source is marked "fix", as the notebook reads it).

Writes sft-train.jsonl, sft-val.jsonl, dpo.jsonl and counts.json (what came from where).
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

OWN_SHARE = 0.20
FLOOR = 25
SEED = 7


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def own(row: dict) -> bool:
    return (row.get("meta") or {}).get("model", "").startswith("served")


def family(row: dict) -> str:
    return (row.get("meta") or {}).get("family") or "?"


def main(old: Path, new: Path, out: Path) -> None:
    rng = random.Random(SEED)
    train = read(old / "sft-train.jsonl") + read(new / "sft-train.jsonl")
    val = read(old / "sft-val.jsonl") + read(new / "sft-val.jsonl")
    teacher = [r for r in train if not own(r)]
    mine = [r for r in train if own(r)]
    cap = int(OWN_SHARE / (1 - OWN_SHARE) * len(teacher))
    covered = Counter(family(r) for r in teacher)
    by_family: dict[str, list[dict]] = defaultdict(list)
    for r in mine:
        by_family[family(r)].append(r)
    for rows in by_family.values():
        rng.shuffle(rows)
    kept: list[dict] = []
    order = sorted(by_family, key=lambda f: covered[f])  # the families the teacher covers least first
    while len(kept) < cap and any(by_family[f] for f in order):
        for f in order:
            if by_family[f] and len(kept) < cap:
                kept.append(by_family[f].pop())
    rows = teacher + kept
    have = Counter(family(r) for r in rows)
    topped = {}
    for f, n in sorted(have.items()):
        if n < FLOOR and f != "?":
            pool = [r for r in rows if family(r) == f]
            extra = [dict(rng.choice(pool)) for _ in range(FLOOR - n)]
            rows += extra
            topped[f] = len(extra)
    rng.shuffle(rows)
    pairs = read(old / "dpo.jsonl") + read(new / "dpo.jsonl")
    for p in pairs:
        p.setdefault("meta", {})
        if not p["meta"].get("source"):
            p["meta"]["source"] = "fix"
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (("sft-train", rows), ("sft-val", val), ("dpo", pairs)):
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    counts = {
        "sft-train": len(rows), "sft-val": len(val), "dpo": len(pairs),
        "from": {"v6": len(read(old / "sft-train.jsonl")), "v7-new": len(read(new / "sft-train.jsonl"))},
        "own_runs": {"had": len(mine), "kept": len(kept), "cap": cap},
        "topped_up": topped,
        "families": dict(sorted(Counter(family(r) for r in rows).items())),
        "models": dict(Counter((r.get("meta") or {}).get("model", "?") for r in rows)),
        "dpo_sources": dict(Counter(p["meta"]["source"] for p in pairs)),
    }
    (out / "counts.json").write_text(json.dumps(counts, indent=1))
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main(*(Path(a) for a in sys.argv[1:4]))
