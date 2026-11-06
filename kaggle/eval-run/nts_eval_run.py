"""Run one evaluation plan on Kaggle (GPU T4 x2): a llama-server per GPU, the plan's jobs spread over their slots.

The plan (`kaggle/plans/<PLAN>.json`, in the attached nts-eval-code dataset) lists jobs:
    suites  evaluation.suites with one intents adapter (it takes `workers` slots of one server)
    agent   python -m nts eval with one agent adapter on some families of one department (one slot)
Each job runs in a folder of its own (its own model cache, store copy and telemetry), so a repeated job is a real
repeat. Jobs are interleaved across adapters, so a run cut short by the time budget still covers every adapter.

Writes /kaggle/working/results/: suites/<job>.jsonl (the leaderboard line), agent/<job>.json (the eval report),
logs/<job>.log, progress.json, servers.json. Telemetry of the agent episodes goes to /kaggle/working/telemetry/.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import urllib.request
import zipfile
from pathlib import Path

PLAN = "__PLAN__"
T0 = time.time()
INP, WORK = Path("/kaggle/input"), Path("/kaggle/working")
RES = WORK / "results"
for d in ("suites", "agent", "logs"):
    (RES / d).mkdir(parents=True, exist_ok=True)


def log(*a):
    print(f"[{(time.time() - T0) / 60:6.1f} min]", *a, flush=True)


def find(name: str) -> list[Path]:
    return sorted(INP.glob(f"**/{name}"))


def sh(cmd: str) -> None:
    log("$", cmd)
    subprocess.run(cmd, shell=True, check=True)


# -- the plan, the code, the tools ---------------------------------------------------------------------------------
# the dataset's top folder: the one holding plans/ (Kaggle unpacks an uploaded zip into a folder of the same name,
# and the unpacked trees carry copies of kaggle/plans too, so take the shortest path)
code = min((p.parent.parent for p in find(f"{PLAN}.json") if p.parent.name == "plans"), key=lambda p: len(p.parts))
plan = json.loads((code / "plans" / f"{PLAN}.json").read_text())
jobs = plan["jobs"]
END = T0 + plan["budget_hours"] * 3600
log(f"plan {PLAN}: {len(jobs)} jobs, budget {plan['budget_hours']} h")

kinds = {j["kind"] for j in jobs}
trees = {"suites": "intents", "agent": "agent"}
deps: set[str] = set()
for kind in kinds:
    t = Path("/tmp") / trees[kind]
    if (code / f"{trees[kind]}.zip").exists():
        with zipfile.ZipFile(code / f"{trees[kind]}.zip") as z:
            z.extractall(t)
    else:  # unpacked by Kaggle on upload
        shutil.copytree(code / trees[kind], t, dirs_exist_ok=True)
    deps |= set(tomllib.loads((t / "pyproject.toml").read_text())["project"]["dependencies"])
sh(f"{sys.executable} -m venv /tmp/venv")
sh("/tmp/venv/bin/pip install -q " + " ".join(f"'{d}'" for d in sorted(deps)))
PY = "/tmp/venv/bin/python"

tools = find("llama-server")
tools = [p for p in tools if p.parent.name == "bin"][0].parent.parent
BIN = Path("/tmp/bin")
BIN.mkdir(exist_ok=True)
shutil.copy2(tools / "bin" / "llama-server", BIN / "llama-server")
os.chmod(BIN / "llama-server", 0o755)
base = next(iter(tools.glob("*.gguf")))
need = sorted({j["adapter"] for j in jobs})
gguf = {}
for a in need:
    hits = find(f"{a}.gguf")
    assert hits, f"no {a}.gguf in the attached notebooks ({plan['kernel_sources']})"
    gguf[a] = hits[0]
log("base", base, "| adapters", {a: str(p) for a, p in gguf.items()})

# -- a server per GPU -----------------------------------------------------------------------------------------------
NP, CTX = plan["server"]["np"], plan["server"]["ctx"]
ports = [8080, 8081]
procs = []
for gpu, port in enumerate(ports):
    args = [str(BIN / "llama-server"), "-m", str(base), "--jinja", "-ngl", "99", "-c", str(CTX), "-np", str(NP),
            "--host", "127.0.0.1", "--port", str(port), "--lora-init-without-apply"]
    for p in gguf.values():
        args += ["--lora", str(p)]
    out = open(RES / "logs" / f"server-{gpu}.log", "w")
    procs.append(subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT,
                                  env={**os.environ, "CUDA_VISIBLE_DEVICES": str(gpu)}))


def get(url: str):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.load(r)


servers = {}
for port in ports:
    for _ in range(600):
        try:
            if get(f"http://127.0.0.1:{port}/health").get("status") == "ok":
                break
        except Exception:  # noqa: BLE001 - loading
            pass
        time.sleep(2)
    loras = get(f"http://127.0.0.1:{port}/lora-adapters")
    names = sorted(Path(x["path"]).stem for x in loras)
    assert set(need) <= set(names), (port, names)
    servers[port] = {"loras": names, "model": get(f"http://127.0.0.1:{port}/v1/models")["data"][0]["meta"]}
(RES / "servers.json").write_text(json.dumps(servers, indent=1))
log("servers up:", {p: len(s["loras"]) for p, s in servers.items()})


# -- the jobs ---------------------------------------------------------------------------------------------------------
def interleave(js: list[dict]) -> list[dict]:
    """Round-robin over adapters, so the first hours cover every adapter a little."""
    groups: dict[str, list[dict]] = {}
    for j in js:
        groups.setdefault(j["adapter"] + j["kind"], []).append(j)
    out, i = [], 0
    while any(groups.values()):
        for g in groups.values():
            if i < len(g):
                out.append(g[i])
        i += 1
        if all(i >= len(g) for g in groups.values()):
            break
    return out


def safe(job_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "__", job_id)


def jobdir(job: dict) -> Path:
    t = Path("/tmp") / trees[job["kind"]]
    d = Path("/tmp/jobs") / safe(job["id"])
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    for name in os.listdir(t):
        if name != "runs":
            os.symlink(t / name, d / name)
    if job["kind"] == "agent":
        (d / "runs" / "agentic").mkdir(parents=True)
        shutil.copy2(t / "runs" / "agentic" / f"{job['store']}.jsonl", d / "runs" / "agentic" / f"{job['store']}.jsonl")
    return d


def command(job: dict, port: int, d: Path) -> list[str]:
    url = f"http://127.0.0.1:{port}/v1"
    if job["kind"] == "suites":
        return [PY, "-m", "evaluation.suites", "--parser", "local", "--local", url, "--adapter", job["adapter"],
                "--workers", str(job["workers"]), "--note", job["id"]]
    return [PY, "-m", "nts", "eval", "--model", "llama", "--url", url, "--adapter", job["adapter"],
            "--agent", job["agent"], "--store", f"runs/agentic/{job['store']}.jsonl", "--seed", str(job["seed"]),
            "--per-family", str(job["per_family"]), "--max-seconds", "900", "--telemetry",
            str(WORK / "telemetry" / safe(job["id"])), "--out", str(RES / "agent" / f"{safe(job['id'])}.json"),
            "--families", *job["families"]]


free = {p: NP for p in ports}
cond = threading.Condition()
done, failed, skipped = [], [], []


def run(job: dict, port: int, units: int) -> None:
    d = jobdir(job)
    t = time.time()
    ok = False
    for attempt in (1, 2):
        with open(RES / "logs" / f"{safe(job['id'])}.log", "w") as out:
            rc = subprocess.run(command(job, port, d), cwd=d, stdout=out, stderr=subprocess.STDOUT,
                                env={**os.environ, "PYTHONPATH": "src", "NTS_PARSER": "local"}).returncode
        text = (RES / "logs" / f"{safe(job['id'])}.log").read_text(errors="replace")
        ok = rc == 0 and "model_error" not in text
        if ok:
            break
        log(f"retry {job['id']} (rc {rc})")
    if job["kind"] == "suites":
        lb = d / "runs" / "leaderboard.jsonl"
        if lb.exists():
            shutil.copy2(lb, RES / "suites" / f"{safe(job['id'])}.jsonl")
    with cond:
        (done if ok else failed).append({"id": job["id"], "port": port, "minutes": round((time.time() - t) / 60, 1)})
        free[port] += units
        cond.notify_all()
    log(f"{'done' if ok else 'FAILED'} {job['id']} on :{port} in {(time.time() - t) / 60:.1f} min "
        f"({len(done)} done, {len(failed)} failed of {len(jobs)})")
    (RES / "progress.json").write_text(json.dumps({"done": done, "failed": failed, "skipped": skipped}, indent=1))


threads = []
for job in interleave(jobs):
    units = job.get("workers", 1) if job["kind"] == "suites" else 1
    with cond:
        while True:
            if time.time() > END:
                break
            port = max(ports, key=lambda p: free[p])
            if free[port] >= units:
                free[port] -= units
                break
            cond.wait(timeout=30)
    if time.time() > END:
        skipped.append(job["id"])
        continue
    th = threading.Thread(target=run, args=(job, port, units), daemon=True)
    th.start()
    threads.append(th)
for th in threads:
    th.join()
(RES / "progress.json").write_text(json.dumps({"done": done, "failed": failed, "skipped": skipped}, indent=1))
for p in procs:
    p.terminate()
log(f"finished: {len(done)} done, {len(failed)} failed, {len(skipped)} skipped (budget)")
