# Running it

## What you need

- **Python 3.11+** and [uv](https://docs.astral.sh/uv/).
- **Node.js and npm** on `PATH`: `nts-web` builds the front end when it starts.
- **Optional, for the fine-tuned models**: llama.cpp's `llama-server` with a GPU, the base GGUF
  (`Qwen3.5-4B-Base-Q8_0.gguf`) and the adapters' GGUF files. Without it the app runs on its rule-based stand-ins.
- **Optional, for Gemini**: API keys in `.env` (`GEMINI_API_KEY`, or several comma-separated, or
  `GEMINI_API_KEY_1`, `_2`, …). Never commit `.env`.

## Quick start

```sh
uv sync                          # create .venv and install dependencies
uv run pytest -m "not slow"      # fast tests
uv run nts-web                   # the app on http://127.0.0.1:8000, offline (no model needed)
```

Sign in by choosing a person (a teacher, the HOD, a class representative, the timetable office, …). Several tabs
can be signed in as different people at once.

## Three ways to run the app

| Mode | Command | Reads with |
|---|---|---|
| Offline (default) | `uv run nts-web` | The rule parser, the rule-based policy check, the regex question reader, template explanations |
| Local model | `uv run nts-web --parser local` | The fine-tuned adapters on `llama-server` (stand-ins whenever it can't be reached) |
| Gemini | `uv run nts-web --parser gemini` | Gemini for every task (stand-ins when the quota is spent) |

Other options: `--rebuild` (rebuild the front end), `--no-build` (serve `frontend/dist` as it is),
`--test-data N` (seed N test requests). For front-end development, run `npm run dev` in `frontend/` and open
http://localhost:5173; it forwards `/api` to port 8000.

## Serving the models

Start `llama-server` with the base and every adapter, none applied until a call asks for it:

```sh
llama-server -m Qwen3.5-4B-Base-Q8_0.gguf \
  --lora nts-intents-v12-read-100.gguf,nts-read100.gguf,nts-lookup-v3.gguf,nts-memory-v1.gguf \
  --lora-init-without-apply --jinja -ngl 99 -c 8192 --cache-ram 1024 --host 0.0.0.0 --port 8080
```

- `--cache-ram 1024` caps the prompt cache in RAM; without it a long evaluation can grow the server until it is
  killed.
- Check it with `curl http://<host>:8080/v1/models` and `curl http://<host>:8080/lora-adapters`.
- Point the app at it with `NTS_LOCAL_URL=http://<host>:8080/v1`.
- Which adapter does which task is `adapters-lora.toml`; to try another lookup adapter, change one line
  (`nts-lookup-v4 = ["lookup"]`) or point `NTS_ADAPTERS` at a copy.

If the server drops (a network blip, a restart), the app carries on with the stand-ins and goes back to the model
by itself when it returns; requests that would change the timetable wait for it for up to 10 minutes.

## Configuration

| Variable | Default | What it does |
|---|---|---|
| `NTS_PARSER` | `offline` | `offline`, `local` or `gemini` (as `--parser`) |
| `NTS_LOCAL_URL` | `http://localhost:8080/v1` | The `llama-server` address |
| `NTS_ADAPTERS` | `adapters-lora.toml` | The adapter → task file |
| `NTS_DOMAIN` | | Another institute's adapters (a `[domains.<name>]` section) |
| `NTS_LOCAL_MODEL` | | A model name, for a server that serves several models |
| `NTS_LOCAL_TIMEOUT` | `120` | Seconds before a model call gives up |
| `NTS_LOCAL_CONCURRENCY` | `4` | Model calls at once |
| `NTS_HOLD_MINUTES` | `10` | How long a request waits for the model before the stand-in reads it |
| `NTS_LOOKUP_READER` | | `model` or `regex`, to force who reads timetable questions |
| `NTS_MEMORY` | | `off` turns follow-up memory off |
| `NTS_RETRIEVER` | `hybrid` | `bm25`, `dense` or `hybrid` rule retrieval |
| `NTS_OCR`, `NTS_OCR_URL` | `rapidocr` | OCR for scanned policy documents (`unlimited` uses a GPU server) |
| `NTS_POLICY_DIR` | `data/policies` | Where policy documents are |
| `NTS_SEMESTER_DIR`, `NTS_SEMESTER_TIME` | `runs/semester`, `60` | The semester planner's state, and its solve time in seconds |
| `NTS_REPLY_DEADLINE` | `900` | Seconds a person has to answer a negotiation message |
| `NTS_PERSIST` | on for `nts-web` | Each world's state survives a restart (`runs/state/`); `0` starts fresh every time |
| `NTS_HOST`, `NTS_PORT` | `127.0.0.1`, `8000` | Where the app listens |
| `NTS_BUILD` | | `0` skips the front-end build |

## Tests

```sh
uv run pytest -m "not slow"      # every test but the full-department solves
uv run pytest                    # everything
uv run pytest tests/test_chat.py # one area
```

There is one test file per area (`tests/`). Tests that need a model use fake ones, so the whole suite runs offline
and with no API keys. Tests marked `slow` run real solves in background threads.

## Evaluations

The commands are listed in [evaluation.md](evaluation.md#running-the-evaluations). Every model answer is cached
(by model and prompt), so a run stopped by a network drop or a spent quota continues where it stopped, and any
result can be scored again without calling a model.

## Where things are kept

| Path | What |
|---|---|
| `runs/` | Caches, evaluation results, the app's saved state, the semester plan (not committed) |
| `runs/worlds/` | Departments built from offering documents, rebuilt at start-up |
| `runs/ocr_cache/`, `runs/embed_models/` | OCR results, the embedding model |
| `frontend/dist/` | The built front end |
