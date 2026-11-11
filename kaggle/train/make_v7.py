"""nts-agent-v7: v6's notebook (its code and Docker image, the DPO_PARALLEL "data" fix of nts-agent-v6-dpo) on the
agent-v7 data, in two sessions, with the recipe the earlier runs point to (docs/improvement-plan.md; kaggle-logs):

    python kaggle/train/make_v7.py      # kaggle/push/data-agent-v7/, train-agent-v7/ (SFT), train-agent-v7-dpo/ (DPO)

* SFT from the base, **1 epoch, cosine to zero** (CURVE = []). v6 trained 2 epochs at a constant rate: its second
  epoch moved the validation loss 3% (0.1377 -> 0.1335) and scored no better on the new families (22 vs 21 of 24),
  and the two epochs took 6.6 h of the session, leaving DPO no time (it ran out 16 steps in). One annealed epoch
  is about half the time and ends where the rate is low, as the intents' cosine runs did best.
* DPO in a session of its own on that SFT adapter (DPO_ONLY = "auto", the SFT notebook's output attached), on
  outcome **and** fix pairs (v6: outcome only, 343 pairs), at 5e-5 (v6: 2e-5, its loss stayed near ln 2: 0.694 ->
  0.652, held-out accuracy 0.65). Both adapters are exported; the release rule picks between them.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = HERE / "agent-v6-pulled"
PUSH = HERE.parent / "push"
ACCOUNT = "seronic2001"
ADAPTER = "nts-agent-v7"
DATASET = "nts-agent-v7-data"
COMMON = {"ADAPTER": f'"{ADAPTER}"', "EPOCHS": "1", "CURVE": "[]", "LR": "2e-4"}
SESSIONS = {
    "train-agent-v7": (ADAPTER, {**COMMON, "DPO": "False", "DPO_ONLY": "None"}, []),
    "train-agent-v7-dpo": (f"{ADAPTER}-dpo", {**COMMON, "DPO": "True", "DPO_ONLY": '"auto"',
                                              "DPO_SOURCES": '["outcome", "fix"]', "DPO_LR": "5e-5"},
                           [f"{ACCOUNT}/{ADAPTER}"]),
}


def dataset(data: Path) -> Path:
    d = PUSH / "data-agent-v7"
    d.mkdir(parents=True, exist_ok=True)
    for f in ("sft-train.jsonl", "sft-val.jsonl", "dpo.jsonl", "counts.json"):
        shutil.copyfile(data / f, d / f)
    (d / "dataset-metadata.json").write_text(json.dumps(
        {"title": DATASET, "id": f"{ACCOUNT}/{DATASET}", "licenses": [{"name": "CC0-1.0"}]}, indent=1))
    return d


def notebook(folder: str, slug: str, settings: dict[str, str], kernels: list[str]) -> Path:
    meta = json.loads((SRC / "kernel-metadata.json").read_text())
    nb = json.loads((SRC / meta["code_file"]).read_text(encoding="utf-8"))
    src = "".join(nb["cells"][4]["source"])
    for key, value in settings.items():
        src, n = re.subn(rf"^{key} = [^#\n]*", f"{key} = {value}  ", src, flags=re.M)
        assert n == 1, key
    nb["cells"][4]["source"] = src.splitlines(keepends=True)
    for c in nb["cells"]:  # markdown cells have no outputs: a None there fails papermill after the run
        if c["cell_type"] == "code":
            c["outputs"], c["execution_count"] = [], None
        else:
            c.pop("outputs", None)
            c.pop("execution_count", None)
    d = PUSH / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.ipynb").write_text(json.dumps(nb, indent=1), encoding="utf-8")
    m = {k: v for k, v in meta.items() if k != "id_no"}
    m.update(id=f"{ACCOUNT}/{slug}", title=slug, code_file=f"{slug}.ipynb", kernel_sources=kernels,
             dataset_sources=[f"{ACCOUNT}/{DATASET}"])
    (d / "kernel-metadata.json").write_text(json.dumps(m, indent=1))
    return d


if __name__ == "__main__":
    import sys

    print(dataset(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "agent-v7"))
    for folder, (slug, settings, kernels) in SESSIONS.items():
        print(notebook(folder, slug, settings, kernels))
