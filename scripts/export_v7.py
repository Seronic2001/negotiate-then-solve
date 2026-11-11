"""The v7 collection's rows (python scripts/export_v7.py runs/telemetry-v7-all data/agent-v7-new).

Best of 3 judges only the run it keeps; a run not kept that wrote the same draft (``same_draft``) leaves the same
committed state, so a family whose checks read only that state passes it as the kept one did. Those runs are
labelled with the kept run's verdict; the question family (whose check reads the reply) keeps only judged runs.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "src")
from nts.data import episodes, export  # noqa: E402

TEXT_CHECKED = {"q_colleague_free"}


def main(telemetry: Path, out: Path) -> None:
    eps = [e for e in episodes(telemetry / "spans") if "gemini" in e.model]
    verdict: dict[str, tuple[bool, str]] = {}  # the kept run's episode id -> (passed, family)
    for e in eps:
        if e.evaluations:
            a = e.evaluations[-1].attrs
            verdict[e.id] = (bool(a.get("passed")), a.get("family"))
    lifted = Counter()
    for e in eps:
        if e.evaluations or not e.selections:
            continue
        s = e.selections[-1].attrs
        got = verdict.get(s.get("chosen_id", ""))
        if s.get("chosen") or not s.get("same_draft") or got is None or got[1] in TEXT_CHECKED:
            continue
        passed, family = got
        label = {"good": passed, "why": f"same draft as the kept run ({'passed' if passed else 'failed'})",
                 "family": family, "status": e.episode.attrs.get("status")}
        e.label = (lambda lab: (lambda: lab))(label)
        lifted[(family, passed)] += 1
    counts = export(eps, out)
    counts["lifted"] = {f"{f}:{'good' if p else 'bad'}": n for (f, p), n in sorted(lifted.items())}
    (out / "counts.json").write_text(json.dumps(counts, indent=1))
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
