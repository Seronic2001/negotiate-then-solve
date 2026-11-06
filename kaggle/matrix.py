"""The Phase 0 regression matrix from the eval kernels' results (python kaggle/push_eval.py fetch first).

    python kaggle/matrix.py                     # writes docs/regression-matrix.md

Intents: outcome match per suite and adapter (and the leaderboard's older runs on the same suites, by fingerprint).
Agent: pass rate per family and adapter, over both departments; each cell is passed/n.
Noise: a job run twice (v12-e3 r0/r1/r2; v6-dpo on both accounts) gives the band; a difference within it is noise.
Release rule: a candidate fails if any suite or family is below the best earlier adapter by more than the band.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parents[1] / "kaggle-results"
OUT = HERE.parent / "docs" / "regression-matrix.md"


def wilson(p: int, n: int) -> str:
    if n == 0:
        return ""
    z, ph = 1.96, p / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return f"[{max(0, c - h):.2f}, {min(1, c + h):.2f}]"


def intents() -> tuple[dict, list[str]]:
    cells: dict[str, dict[str, float]] = defaultdict(dict)
    for f in RESULTS.glob("*/results/suites/*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            tag = r["note"].removeprefix("suites/")
            for s, v in r["suites"].items():
                cells[s][tag] = v["outcome_match"]
    cols = sorted({t for c in cells.values() for t in c}, key=lambda t: (t.split("/")[0], t))
    return cells, cols


def agent() -> tuple[dict, list[str]]:
    cells: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for f in RESULTS.glob("*/results/agent/*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        parts = f.stem.split("__")  # agent / tag / store / family [/ rN]
        tag = parts[1] + (f"/{parts[4]}" if len(parts) > 4 else "")
        for v in d["verdicts"]:
            c = cells[v["family"]][tag]
            c[0] += v["passed"]
            c[1] += 1
    cols = sorted({t for c in cells.values() for t in c})
    return cells, cols


def main() -> None:
    L = ["# Regression matrix (Phase 0)", "", f"From `{RESULTS}`.", ""]
    ic, icols = intents()
    if ic:
        L += ["## Intents: outcome match per suite", "", "| suite | " + " | ".join(icols) + " |",
              "|---|" + "---|" * len(icols)]
        for s in sorted(ic, key=lambda s: (not s.startswith("test"), s)):
            L.append(f"| {s} | " + " | ".join(f"{ic[s][c]:.3f}" if c in ic[s] else "" for c in icols) + " |")
        reps = [c for c in icols if c.startswith("v12-e3")]
        if len(reps) > 1:
            band = {s: max(ic[s].get(c, 0) for c in reps) - min(ic[s].get(c, 0) for c in reps) for s in ic}
            L += ["", f"Noise (v12-e3 run {len(reps)}x): widest spread {max(band.values()):.3f}; per suite "
                  + ", ".join(f"{s} {b:.3f}" for s, b in sorted(band.items()) if b > 0)]
        L.append("")
    ac, acols = agent()
    if ac:
        L += ["## Agent: passed / n per family (both departments)", "", "| family | " + " | ".join(acols) + " |",
              "|---|" + "---|" * len(acols)]
        tot = defaultdict(lambda: [0, 0])
        for fam in sorted(ac):
            row = []
            for c in acols:
                p, n = ac[fam].get(c, [0, 0])
                tot[c][0] += p
                tot[c][1] += n
                row.append(f"{p}/{n}" if n else "")
            L.append(f"| {fam} | " + " | ".join(row) + " |")
        L.append("| **all** | " + " | ".join(f"**{tot[c][0]}/{tot[c][1]}** {wilson(*tot[c])}" for c in acols) + " |")
        pairs = [(a, b) for a in acols for b in acols if a < b and a.split("/")[0] == b.split("/")[0]]
        for a, b in pairs:
            diff = [abs(ac[f].get(a, [0, 0])[0] - ac[f].get(b, [0, 0])[0]) for f in ac]
            L.append(f"\nNoise ({a} vs {b}, the same job twice): {sum(diff)} episodes differ over {len(ac)} families; "
                     f"the widest family differs by {max(diff)}.")
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
