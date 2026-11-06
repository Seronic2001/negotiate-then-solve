"""Upload the code dataset and push eval kernels, each on the account its plan names.

    python kaggle/push_eval.py code                  # create or version <account>/nts-eval-code on both accounts
    python kaggle/push_eval.py run a-intents a-agent # push nts-eval-<plan> for each plan (GPU T4 x2, internet on)
    python kaggle/push_eval.py status                # the kernels' status
    python kaggle/push_eval.py fetch                 # results only (results/**: JSON and logs; never weights)

seronic2001 runs with USERPROFILE pointing at C:/Users/Shubh/kaggle_home_seronic (its .kaggle is that account's
credentials); the CLI ignores KAGGLE_CONFIG_DIR. Paths go to the CLI in Windows form.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUSH = HERE / "push"
HOMES = {"shubhadeepmandal": None, "seronic2001": r"C:\Users\Shubh\kaggle_home_seronic"}
RESULTS = HERE.parents[1] / "kaggle-results"


def kaggle(account: str, *args: str, check: bool = True) -> str:
    env = dict(os.environ)
    if HOMES[account]:
        env["USERPROFILE"] = HOMES[account]
    p = subprocess.run(["uvx", "--with", "six", "kaggle", *args], env=env, capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip()
    if check and p.returncode != 0:
        raise SystemExit(f"kaggle {' '.join(args)} ({account}) failed:\n{out}")
    return out


def code() -> None:
    for account in HOMES:
        d = str(PUSH / f"code-{account}")
        listed = kaggle(account, "datasets", "list", "--mine", "-s", "nts-eval-code", check=False)
        if f"{account}/nts-eval-code" in listed:
            print(account, kaggle(account, "datasets", "version", "-p", d, "-m", "update", "-r", "skip", "-q")[-200:])
        else:
            print(account, kaggle(account, "datasets", "create", "-p", d, "-r", "skip", "-q")[-200:])


def run(names: list[str]) -> None:
    for name in names:
        plan = json.loads((HERE / "plans" / f"{name}.json").read_text())
        account = plan["account"]
        d = PUSH / f"eval-{name}"
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        src = (HERE / "eval-run" / "nts_eval_run.py").read_text().replace('PLAN = "__PLAN__"', f'PLAN = "{name}"')
        (d / "nts_eval_run.py").write_text(src)
        (d / "kernel-metadata.json").write_text(json.dumps({
            "id": f"{account}/nts-eval-{name}", "title": f"nts-eval-{name}", "code_file": "nts_eval_run.py",
            "language": "python", "kernel_type": "script", "is_private": True, "enable_gpu": True,
            "enable_internet": True, "machine_shape": "NvidiaTeslaT4",
            "dataset_sources": [f"{account}/nts-eval-code"], "kernel_sources": plan["kernel_sources"],
            "competition_sources": []}, indent=1))
        print(name, "->", kaggle(account, "kernels", "push", "-p", str(d))[-160:])


def status() -> None:
    for f in sorted((HERE / "plans").glob("*.json")):
        plan = json.loads(f.read_text())
        print(f"{f.stem:12} {plan['account']:17}",
              kaggle(plan["account"], "kernels", "status", f"{plan['account']}/nts-eval-{f.stem}", check=False)[-90:])


def fetch() -> None:
    for f in sorted((HERE / "plans").glob("*.json")):
        plan = json.loads(f.read_text())
        dest = RESULTS / f.stem
        dest.mkdir(parents=True, exist_ok=True)
        kaggle(plan["account"], "kernels", "output", f"{plan['account']}/nts-eval-{f.stem}", "-p", str(dest), "-q",
               "-o", "--file-pattern", r"(^|/)results/|\.log$", check=False)
        print(f.stem, sum(1 for _ in dest.rglob("*") if _.is_file()), "files")


if __name__ == "__main__":
    cmd, rest = sys.argv[1], sys.argv[2:]
    {"code": lambda: code(), "run": lambda: run(rest), "status": lambda: status(), "fetch": lambda: fetch()}[cmd]()
