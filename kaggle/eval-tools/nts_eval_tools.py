"""Tools for evaluating NTS adapters on Kaggle (GPU T4 x2), built once per account and attached to every eval run.

Writes to /kaggle/working/tools:
    bin/llama-server, bin/llama-quantize   llama.cpp b11368 (the GPU server's build), CUDA for the T4 (sm_75), static
    Qwen3.5-4B-Q8_0.gguf                  the base the adapters were trained on (Qwen/Qwen3.5-4B), Q8_0
    tools.json                            what was built, and the base's parameter count as the server reports it

The GPU server's base (Qwen3.5-4B-Base-Q8_0.gguf) reports n_params 4,205,751,296; the conversion is tried as is and
then with --no-mtp, and the one that loads with that count is kept.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

T0 = time.time()
OUT = Path("/kaggle/working/tools")
(OUT / "bin").mkdir(parents=True, exist_ok=True)
SRC = Path("/tmp/llama.cpp")
TAG = "b11368"
TARGET_PARAMS = 4_205_751_296
info = {"llama_cpp": TAG, "cuda_arch": "75"}


def sh(cmd, **kw):
    print(f"[{time.time() - T0:6.0f}s] $ {cmd}", flush=True)
    subprocess.run(cmd, shell=True, check=True, **kw)


sh("nvidia-smi --query-gpu=name,memory.total --format=csv")
sh(f"git clone --depth 1 --branch {TAG} https://github.com/ggml-org/llama.cpp {SRC}")
cuda = next((p for p in ("/usr/local/cuda/bin/nvcc", shutil.which("nvcc") or "") if p and Path(p).exists()), None)
print("nvcc:", cuda, flush=True)
# CUDA 13 on the Kaggle image: CMake finds no libcuda (the driver) to link CUDA::cuda_driver against unless it is
# pointed at the toolkit's stub; failing that, build without the driver API (no virtual memory pool)
stubs = next((p for p in ("/usr/local/cuda/lib64/stubs", "/usr/local/cuda/targets/x86_64-linux/lib/stubs")
              if Path(p, "libcuda.so").exists()), None)
print("libcuda stub:", stubs, flush=True)
configure = (f"cmake -S {SRC} -B {SRC}/build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=75 -DGGML_NATIVE=OFF "
             f"-DBUILD_SHARED_LIBS=OFF -DLLAMA_CURL=OFF -DCMAKE_BUILD_TYPE=Release"
             + (f" -DCMAKE_CUDA_COMPILER={cuda}" if cuda else "")
             + (f" -DCMAKE_LIBRARY_PATH={stubs} -DCUDA_cuda_driver_LIBRARY={stubs}/libcuda.so" if stubs else ""))
try:
    sh(configure)
    info["cuda_driver"] = "stub"
except subprocess.CalledProcessError:
    shutil.rmtree(SRC / "build", ignore_errors=True)
    sh(configure + " -DGGML_CUDA_NO_VMM=ON")
    info["cuda_driver"] = "none (GGML_CUDA_NO_VMM)"
sh(f"cmake --build {SRC}/build --config Release --target llama-server llama-quantize -j {os.cpu_count() or 4}")
for b in ("llama-server", "llama-quantize"):
    shutil.copy2(SRC / "build" / "bin" / b, OUT / "bin" / b)
info["build_seconds"] = round(time.time() - T0)

# the base, as the adapters were trained on it
sh(f"{sys.executable} -m pip install -q -U 'transformers>=5' huggingface_hub safetensors sentencepiece {SRC}/gguf-py")
from huggingface_hub import snapshot_download  # noqa: E402

base_dir = snapshot_download("Qwen/Qwen3.5-4B", allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model",
                                                                 "*.jinja", "tokenizer*"])


def params_of(gguf: Path) -> int | None:
    """Load it in the server on GPU 0 and read n_params back; None when it does not load."""
    log = open("/tmp/probe.log", "w")
    p = subprocess.Popen([str(OUT / "bin" / "llama-server"), "-m", str(gguf), "-ngl", "99", "-c", "2048",
                          "--port", "8099"], stdout=log, stderr=subprocess.STDOUT,
                         env={**os.environ, "CUDA_VISIBLE_DEVICES": "0"})
    try:
        for _ in range(240):
            time.sleep(1)
            if p.poll() is not None:
                return None
            try:
                with urllib.request.urlopen("http://127.0.0.1:8099/v1/models", timeout=2) as r:
                    m = json.load(r)
                return int(m["data"][0]["meta"]["n_params"])
            except Exception:  # noqa: BLE001 - not up yet
                continue
        return None
    finally:
        p.terminate()
        p.wait(timeout=30)
        print(open("/tmp/probe.log").read()[-1500:], flush=True)


final = OUT / "Qwen3.5-4B-Q8_0.gguf"
for extra in ([], ["--no-mtp"]):
    tmp = Path("/tmp/base.gguf")
    sh(f"{sys.executable} {SRC}/convert_hf_to_gguf.py {base_dir} {' '.join(extra)} --outtype q8_0 --outfile {tmp}")
    n = params_of(tmp)
    print("converted with", extra or "defaults", "-> n_params", n, flush=True)
    info.setdefault("tries", []).append({"flags": extra, "n_params": n})
    if n is not None:
        shutil.move(tmp, final)
        info.update(base=final.name, base_flags=extra, n_params=n, matches_gpu_server=n == TARGET_PARAMS)
        if n == TARGET_PARAMS:
            break
    if tmp.exists():
        tmp.unlink()

info["seconds"] = round(time.time() - T0)
(OUT / "tools.json").write_text(json.dumps(info, indent=2))
print(json.dumps(info, indent=2), flush=True)
assert final.exists(), "no base GGUF loaded in the server"
