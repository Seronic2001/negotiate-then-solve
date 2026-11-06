"""Keep both Kaggle accounts' two GPU sessions busy: push the next kernel whenever a session is free and its inputs
are ready. Prints one line per change (a monitor reads them); stops when the queue is empty and nothing runs.

    python kaggle/kaggle_queue.py   # the queue below, polled every 2 minutes

Kaggle allows 2 GPU sessions at a time per account ("Maximum batch GPU session count of 2"). An eval kernel waits
for the notebooks it attaches (the tools, the adapters it scores) to be COMPLETE; a training variant needs nothing.
A kernel that ends in ERROR is reported and its dependants are held (fix it, then rerun the queue).
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from push_eval import kaggle, run as push_plan  # noqa: E402

A, B = "shubhadeepmandal", "seronic2001"
# (account, kernel slug, how to push it, what it waits for)
# trimmed 2026-11-06: dropped cos2, cos2-lr1e4 and b-agent2 (low information)
QUEUE = [
    (A, "nts-eval-a-intents", ("plan", "a-intents"), [f"{A}/nts-eval-tools"]),
    (A, "nts-eval-a-agent", ("plan", "a-agent"), [f"{A}/nts-eval-tools"]),
    (A, "nts-intents-v12-cos1", ("train", "cos1"), []),
    (A, "nts-eval-a-train-eval", ("plan", "a-train-eval"),
     [f"{A}/nts-eval-tools"] + [f"{A}/nts-intents-v12-{v}" for v in ("cos3", "cos1")]),
    (B, "nts-eval-b-agent1", ("plan", "b-agent1"), [f"{B}/nts-eval-tools"]),
]
# started by hand before the queue: they hold a session until they end
WATCH = {A: [f"{A}/nts-eval-tools", f"{A}/nts-intents-v12-cos3"], B: [f"{B}/nts-eval-tools"]}
ACTIVE = ("RUNNING", "QUEUED", "NEW")


def status(account: str, ref: str) -> str:
    out = kaggle(account, "kernels", "status", ref, check=False)
    for s in ("COMPLETE", "ERROR", "CANCEL", "RUNNING", "QUEUED", "NEW"):
        if f"KernelWorkerStatus.{s}" in out or f'"{s.lower()}"' in out.lower():
            return s
    return "UNKNOWN"


def push(account: str, how: tuple[str, str]) -> str:
    kind, name = how
    if kind == "plan":
        try:
            push_plan([name])
        except SystemExit as e:  # the CLI refused (e.g. both sessions busy): report it, try again later
            return f"error: {e}"
        return "pushed"
    d = HERE / "push" / f"train-{name}"
    return kaggle(account, "kernels", "push", "-p", str(d), check=False)[-120:]


def main() -> None:
    pending = list(QUEUE)
    watched = {acct: list(refs) for acct, refs in WATCH.items()}
    last: dict[str, str] = {}
    while True:
        states = {ref: status(acct, ref) for acct, refs in watched.items() for ref in refs}
        for ref, s in states.items():
            if last.get(ref) != s:
                print(f"{time.strftime('%H:%M')} {ref}: {s}", flush=True)
                last[ref] = s
        for acct in (A, B):
            busy = sum(states.get(r) in ACTIVE for r in watched[acct])
            for item in [i for i in pending if i[0] == acct]:
                if busy >= 2:
                    break
                deps = [states.get(d) or status(acct, d) for d in item[3]]
                if any(d in ("ERROR", "CANCEL") for d in deps):
                    print(f"{time.strftime('%H:%M')} HELD {item[1]}: an input ended in {deps}", flush=True)
                    pending.remove(item)
                    continue
                if not all(d == "COMPLETE" for d in deps):
                    continue
                out = push(acct, item[2])
                if "session count" in out.lower():
                    break  # a session we do not track is busy: try again next round
                if "error" in out.lower():
                    print(f"{time.strftime('%H:%M')} PUSH FAILED {acct}/{item[1]}: {out.strip()[-200:]}", flush=True)
                    pending.remove(item)
                    continue
                print(f"{time.strftime('%H:%M')} PUSHED {acct}/{item[1]} ({out.strip()[-60:]})", flush=True)
                pending.remove(item)
                watched[acct].append(f"{acct}/{item[1]}")
                busy += 1
        running = [r for refs in watched.values() for r in refs if states.get(r) in ACTIVE]
        if not pending and not running and states:
            print(f"{time.strftime('%H:%M')} queue empty, nothing running", flush=True)
            return
        time.sleep(120)


if __name__ == "__main__":
    main()
