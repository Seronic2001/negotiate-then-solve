"""Pack the code the Kaggle eval runs need into one private dataset per account (``<account>/nts-eval-code``).

    python kaggle/bundle.py                # writes kaggle/push/code-<account>/ for both accounts

Two zips, from the working trees as they are (tracked and untracked files git does not ignore), without training
data and other large files the evaluations never read:

    intents.zip   negotiate-then-solve-agentic-demo: evaluation.suites, the frozen test and data/suites (intents-v12)
    agent.zip     negotiate-then-solve-agentic-demo: nts eval with the Phase 1 fixes and all 49 families (v7), and
                  the eval departments copied from negotiate-then-solve-agentic
                  (runs/agentic/eval.jsonl, eval-big.jsonl, which git does not track)

and the plans (kaggle/plans/*.json).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
TREES = {"intents": PROJECT / "negotiate-then-solve-agentic-demo", "agent": PROJECT / "negotiate-then-solve-agentic-demo"}
EXTRA = {"agent": ["runs/agentic/eval.jsonl", "runs/agentic/eval-big.jsonl"]}
SKIP_DIRS = ("data/lookup-train", "data/memory-train", "data/multitask", "data/distill", "data/agent-v", "notebooks/",
             "report/", "frontend/", "course-offering/", "before_after/", "kaggle/push/", "proposal/", "docs/")
SKIP_FILES = ("data/compiler-intents/mined.jsonl",)  # train.jsonl stays: the tool picker (nts.harness.pick) trains on it
MAX_BYTES = 8_000_000
ACCOUNTS = ("shubhadeepmandal", "seronic2001")


def files(tree: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=tree, capture_output=True, text=True,
                         check=True).stdout.splitlines()
    keep = []
    for f in out:
        p = tree / f
        if not p.is_file() or f.startswith(SKIP_DIRS) or f in SKIP_FILES or p.stat().st_size > MAX_BYTES:
            continue
        keep.append(f)
    return keep


def pack(name: str, dest: Path) -> dict:
    tree = TREES[name]
    names = files(tree) + [f for f in EXTRA.get(name, []) if (tree / f).is_file()]
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in names:
            z.write(tree / f, f)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=tree, capture_output=True, text=True).stdout.strip()
    return {"tree": tree.name, "head": head, "files": len(names), "bytes": dest.stat().st_size}


def main() -> None:
    stage = HERE / "push" / "code-stage"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    info = {name: pack(name, stage / f"{name}.zip") for name in TREES}
    shutil.copytree(HERE / "plans", stage / "plans")
    (stage / "bundle.json").write_text(json.dumps(info, indent=2))
    for acct in ACCOUNTS:
        d = HERE / "push" / f"code-{acct}"
        shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(stage, d)
        (d / "dataset-metadata.json").write_text(json.dumps(
            {"title": "nts-eval-code", "id": f"{acct}/nts-eval-code", "licenses": [{"name": "other"}]}, indent=2))
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
