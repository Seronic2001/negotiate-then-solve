# Negotiate, Then Solve

Conflict-aware university timetabling with LLM agents and constraint solvers
(LMA Group Project 2026). This repository currently holds the **foundation**
(proposal weeks 1–4): data schemas, a synthetic instance generator, the CP-SAT
model with assumption literals, conflict analysis (MUS/MCS), an independent
validator, an ITC-2007 loader and the labelled request corpus.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                       # create .venv and install dependencies
uv run pytest -m "not slow"   # fast tests (< 1 min)
uv run pytest                 # includes a full department-size solve
uv run python -m nts.demo     # generate a department, solve it, run UC3
```

## Layout

| Module | Proposal | What it does |
|---|---|---|
| `nts/schemas.py` | §7.4, Fig. 2 | `Constraint`, `Request` + lifecycle state machine, `Placement`, `TimetableVersion`, `ConcessionEntry` |
| `nts/instance.py` | §1, §8.3 | Rooms, faculty, groups, sessions, calendar; institute policy as Tier 1 constraints |
| `nts/semantics.py` | §8.3 | What each constraint type means for a placement (shared by solver and validator) |
| `nts/solver.py` | §8.3–8.4 | CP-SAT model; `a_k ⇒ C_k` guards; full build, minimal-change repair, lexicographic tiers |
| `nts/conflicts.py` | §8.5 | `find_mus` (deletion-based shrinking), `enumerate_mcs` (cheapest-first, solver-verified witnesses) |
| `nts/validator.py` | §8.2 step 4, §12.4 | Rejects bad compiled constraints; scores any timetable's hard-constraint validity |
| `nts/generator.py` | §12.1 | Seeded synthetic departments (30 faculty, 60 course sections, 20 rooms by default) |
| `nts/scenarios.py` | §9 | Use-case fixtures (UC3 lab contention so far) |
| `nts/itc.py` | §12.1 | ITC-2007 Track 3 `.ctt` loader and `.sol` writer |
| `nts/corpus.py` | §12.1 | Request corpus generator with labels; JSONL load/save |

## Parsing layer and Gemini

Put the key in `.env` (git-ignored):

```sh
GEMINI_API_KEY=...
# optional overrides (defaults are pinned in nts/llm.py)
GEMINI_MODEL=gemini-3.5-flash-lite       # agent: System Two parser, negotiator
GEMINI_SIM_MODEL=gemini-3.1-flash-lite   # stakeholder simulators, LLM judge
GEMINI_FLASH_MODEL=gemini-3.8-flash      # larger-model comparison set
GEMINI_RPM=15     # requests per minute
GEMINI_RPD=500    # requests per day; the client stops cleanly at this budget
```

Free-tier quotas are per model per day (AI Studio, Sep 2026): Flash-Lite
models 15 RPM / 500 RPD each; Flash models 5 RPM / **20 RPD** each. Bulk runs
therefore use the two Flash-Lite models, which have separate quotas, and
Flash is kept for a small comparison set. A daily-quota 429 stops a run
immediately; rerun the next day and the cache resumes it.

`nts/llm.py` caches every response under `runs/llm_cache/` (keyed by model,
prompts, schema and temperature), so rerunning an experiment costs no quota,
and a run stopped by the daily budget resumes the next day where it stopped.

| Module | Proposal | What it does |
|---|---|---|
| `nts/llm.py` | §14 | Gemini client: structured output, cache, RPM limiter, daily budget, 429 backoff |
| `nts/parsing.py` | §8.2 | System Two parser. The LLM drafts; tiers (Table 5), authority and validation are deterministic |
| `nts/system_one.py` | §8.2 | Calibrated TF-IDF + logistic regression: request type, action, confidence, fast-path routing with τ |
| `nts/metrics.py` | Table 11 | ECE, constraint exact match, atom-level P/R/F1 |
| `nts/eval_parsing.py` | §12 | `uv run python -m nts.eval_parsing --limit 40` |
| `nts/paraphrase.py` | §12.1 | Rewrites the corpus in varied registers with the simulator model; a rule-based check rejects paraphrases that change days, numbers or names |

**Paraphrased corpus.** `uv run python -m nts.paraphrase` writes
`data/requests-para.jsonl`: the same 600 requests and labels, with each text
rewritten (10 per call, about 60 calls) and the template kept in
`template_text`. Injected instructions are cut off before paraphrasing and put
back verbatim. Paraphrases that change a day, number, person, room, group or
course are retried in another style. The check cannot see a wish turning into
a demand, so read a sample by hand. Evaluate on it with
`--corpus data/requests-para.jsonl`; add `--s1-train data/requests.jsonl` to
train System One on templates and test it on paraphrases.

## Policy agent

`nts/policy.py` checks a parsed request against the handbook
(`data/handbook.md`, **a synthetic stand-in**: replace it with the
institute's handbook, one `## <number> <title> [RULE-ID]` heading per rule).

1. BM25 retrieves the top 5 rules. Clock times are normalised ("1pm" and
   "13:00" match), and the query is extended with what the parse implies
   (a one-off absence adds "make-up", a run of more hours than the limit adds
   "consecutive").
2. The LLM returns `allowed`, `needs_approval` or `forbidden`, cited rules,
   obligations (e.g. a make-up class), an explanation and a compliant
   alternative; for policy questions, an answer.
3. Deterministic checks: citations must be among the rules shown, and a
   denial without a valid citation becomes `needs_approval`, so nothing is
   denied without the rule it breaks.

`uv run python -m nts.eval_policy --split val` scores allow/deny accuracy,
citations, make-up obligations and retrieval recall against the corpus
`rules` labels. Use `--policy-model gemini-3.1-flash-lite` for development
when the agent model's daily quota is spent.

| Module | Proposal | What it does |
|---|---|---|
| `nts/policy.py` | L3, UC2, UC4 | Handbook loader, BM25, policy agent with citation checks |
| `nts/eval_policy.py` | Table 11 (RAG) | Parse-then-policy evaluation |

## Fine-tuned compiler (local model)

`uv run python -m nts.compiler` writes `data/compiler/{train,val,test}.jsonl`:
chat examples (short system prompt, compact directory, message) with the gold
`ParseOutput` JSON as the answer. `deny`/`refuse` requests are left out, since
those are decided after parsing. Templated and paraphrased versions of a
request share a split.

`notebooks/train_compiler_kaggle.ipynb` trains it on a Kaggle T4: 16-bit LoRA
on Qwen3.5-4B (Unsloth advises against QLoRA for Qwen3.5), fp16, loss on the
answer only, then exports GGUF (Q5_K_M, about 3.1 GB) for llama.cpp on a 6 GB
laptop GPU. Run it with `TRIAL = True` first.

Evaluate the downloaded model locally with the same harness as Gemini:

```sh
llama-server -m qwen3.5-4b-nts.Q5_K_M.gguf --jinja -ngl 99 -c 4096 --port 8080
uv run python -m nts.eval_parsing --local --corpus data/requests-para.jsonl --split val --limit 100 --workers 1
```

`nts/local.py` talks to any OpenAI-compatible server (llama.cpp, Ollama, LM
Studio), constrains output to the JSON schema, keeps thinking off and caches
like the Gemini client. On a GPU with less memory than the model file, lower
`-ngl` so some layers run on the CPU.

## Data

`uv run python -m nts.corpus` regenerates `data/requests.jsonl` (600 requests,
400/50/150 train/val/test, stratified) and pins the instance it was built
against in `data/synthetic-cse-s0.json`. Each line is a `CorpusExample`:

- `request`: the raw message as it arrives (sender, role, channel, text);
- `request_type`, `authorised`, `expected_action` (`compile`, `clarify`,
  `deny`, `refuse`, `investigate`, `answer`, `out_of_scope`): what System One
  and the policy agent should decide;
- `targets`: the constraints a correct compiler produces. For `clarify`
  examples these are the true constraints behind the vague text, so a
  stakeholder simulator can answer the clarifying question;
- `missing`, `violates_rule`, `injection`: labels for ambiguous,
  rule-breaking and prompt-injection cases;
- `rules`: handbook rules a correct policy check cites (the rule broken, the
  rule a policy question asks about, or P-MAKEUP for a one-off absence).

**Hand-written requests** (the proposal's 100 team-written examples) go in
`data/handwritten.jsonl` in the same format with `"handwritten": true`.
`load_jsonl(path, instance)` rejects any target that names an unknown
faculty member, room or time.

**ITC-2007 instances** (comp01–comp21) come from the CB-CTT benchmark portal
maintained by the University of Udine. Load them with
`nts.itc.load_ctt(Path("comp01.ctt"))`. Room capacity is soft by default,
as in ITC; the ITC soft constraints for working days, compactness and room
stability are not modelled.

## Key conventions

- **Tier 0** rules (each session once, no room/faculty/group clash, compatible
  room) are built into the model and never switched off.
- Every other **hard** constraint gets an assumption literal. `TimetableSolver.core()`
  and `find_mus()` work only over these, so a conflict is always stated in
  terms of constraints someone owns.
- **Soft** constraints (Tier 5 preferences; `prefer`/`avoid` only) and, in
  repair mode, moved sessions form the objective.
- **Weeks.** `week=None` solves the semester-wide timetable with permanent
  constraints only. `week=7` adds constraints valid in week 7; pass the base
  timetable as `baseline=` so the repair stays local.
- `enumerate_mcs` only drops constraints in `relaxable_tiers` (default Tiers
  3–4). Tier 1–2 options need a human with authority and go through
  escalation instead.

## Next steps (proposal timeline)

- Weeks 3–4 (remaining): 100 hand-written requests checked by two annotators; swap requests.
- Weeks 5–6 (remaining): train the compiler (Kaggle notebook) and a local client for it; the institute's real handbook; a dense
  retriever for the BM25 + embedding hybrid.
- Weeks 7–8: priority scores π_k, resolution ladder, concession ledger, grounded explainer.
