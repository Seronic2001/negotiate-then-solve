# Negotiate, Then Solve

Conflict-aware university timetabling with LLM agents and constraint solvers
(LMA Group Project 2026). Every layer of the proposal's architecture is
implemented: channels and the request store (L0–L1), System One / System Two
parsing and the fine-tuned compiler (L2), the policy agent (L3), CP-SAT with
conflict analysis (L4), the interpretation layer with the resolution ladder,
grounded explanations and the concession ledger (L5), and human approval
before publishing (L6). The evaluation harness covers the negotiation
benchmark (baselines B1–B4, ablations A1–A3), parsing, policy and the safety set.

Every LLM-backed component has a deterministic path (template explanations,
scripted simulators, stub parsers), so the whole system can be developed and
tested without API calls; the Gemini free-tier quota is kept for experiments.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                       # create .venv and install dependencies
uv run pytest -m "not slow"   # fast tests (< 1 min)
uv run pytest                 # includes a full department-size solve
uv run python -m nts.demo     # generate a department, solve it, run UC3
uv run uvicorn nts.api:demo_app --factory   # portal on http://127.0.0.1:8000 (no API key)
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
| `nts/scenarios.py` | §9 | UC3 lab-contention fixture (the benchmark generalises it) |
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

`notebooks/train_compiler_kaggle.ipynb` trains it on a Kaggle T4 with LoRA
(Unsloth advises against QLoRA for Qwen3.5), loss on the answer only, then
exports GGUF for llama.cpp on a 6 GB laptop GPU. On a T4, Unsloth runs
Qwen3.5 in float32 (no bf16, and fp16 hits a dtype mismatch), where the 4B
model needs about 18 GB and runs out of memory; the notebook therefore
defaults to **Qwen3.5-2B**. For 4B, use a GPU with bf16 or set
`load_in_4bit = True` (QLoRA, with Unsloth's caveat). Run it with
`TRIAL = True` first.

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

## Interpretation layer (L5): negotiation

| Module | Proposal | What it does |
|---|---|---|
| `nts/priority.py` | §8.4 | π_k = auth + impact + justification + lead + credit − disruption; option cost = Σπ + λ1·moved + λ2·ΔGini; `flat=True` for ablation A2 |
| `nts/ledger.py` | §8.6 | Concession ledger with semester decay; Gini coefficient |
| `nts/explainer.py` | §8.7 | Conflict → numbered facts (MUS constraints, rules, rooms, options, ledger). Template, grounded (claims cite facts; a checker drops claims whose days, numbers or names are not in the cited facts) and free (A3) modes; private-reason leak check |
| `nts/negotiation.py` | §8.6 | Resolution ladder: auto-substitute → auto-relax (notices) → negotiate over MCS options (2–3 solver-verified alternatives per message, cheapest owner first, lowest credit on ties, one extra probe after a refusal) → escalate with a brief. Replies: accept / counter / reject / no reply |
| `nts/simulators.py` | §12.1 | Stakeholders with hidden flexibility (acceptable windows, room flexibility, whether they volunteer it, whether they reply); scripted or LLM-voiced replies |
| `nts/benchmark.py` | §12.1 | 60 scenarios: contention, substitute, deadlock, Tier 3 vs 4 squeeze, capacity shortfall, preference trade-off, policy; the oracle (B4) tries every hidden-flexibility combination |
| `nts/eval_negotiation.py` | §12.2–12.5 | Runs ours / A1–A3 / B1–B4; validity, correct outcome, rounds, cost vs oracle, escalation P/R, concession Gini, faithfulness, leaks; McNemar, Wilcoxon, bootstrap CIs |
| `nts/judge.py`, `nts/stats.py` | §12.5 | Batched LLM judge (clarity, acceptability) and quadratic-weighted Cohen's κ against human raters |

```sh
uv run python -m nts.benchmark                                  # data/scenarios.jsonl (about 30 s)
uv run python -m nts.eval_negotiation --offline                 # ours, A2, B2, B4: no API calls (about 6 min)
uv run python -m nts.eval_negotiation --configs ours-llm,A1,A3,B1,B3   # Gemini; spread over days
uv run python -m nts.judge runs/negotiation-XXXX.json           # LLM judge (batched, Flash-Lite)
uv run python -m nts.judge --kappa data/human_ratings.csv       # judge vs human raters
```

Offline results so far (60 scenarios; `runs/negotiation-offline.json`,
`runs/negotiation-ours-probe.json`):

| | Correct outcome | Valid timetables | Rounds (agreements) | Within 10% of oracle | Escalation P / R | Concession Gini |
|---|---|---|---|---|---|---|
| Ours (MCS, tiers, ledger, probing) | 95% | 100% | 1.56 | 100% | 0.85 / 1.00 | 0.23 |
| A2: flat weights, no ledger | 93% | 100% | 1.53 | 100% | 0.81 / 1.00 | 0.27 |
| B2: solver imposes, no negotiation | 18% | 100% | 0 | – | 1.00 / 0.47 | – |
| B4: oracle | 100% | 100% | 0 | 100% | 1.00 / 1.00 | – |

The A2 row is from the run before probing was added; rerun it for a
like-for-like comparison. Under B2 only 4% of imposed changes would have been
acceptable to their owners. The three scenarios ours escalates although the
oracle agrees are stakeholders who accept only one narrow window and never
say so; six offered alternatives missed it. LLM configurations (ours-llm, A1,
A3, B1, B3) need the API; a 3-scenario smoke run already shows the free
explanation (A3) leaking a private reason, and the LLM-only timetable (B1)
silently breaking requesters' hard constraints.

## Orchestrator, channels and approval (L0, L1, L6)

| Module | Proposal | What it does |
|---|---|---|
| `nts/orchestrator.py` | Fig. 2, §8.9 | The request lifecycle end to end; System One routing; refusal, denial, clarification, escalation, answer and forward exits; fairness audit; publishing only through `approve()` by a listed approver; notifications to affected people only |
| `nts/store.py` | L1, state | SQLite: requests (with dedupe), constraint records, timetable versions (per week, with rollback), ledger, audit log |
| `nts/graph.py` | §8.8 | NetworkX knowledge graph: owns, references, has_authority_over, reports_to, derived_from, conflicts_with, affects, balance |
| `nts/ingest.py` | L0 | Email (RFC 822, IMAP poller), messaging (Slack-shaped JSON) and portal adapters; email → person → role; unknown senders rejected; quoted replies stripped; threading |
| `nts/api.py` | L0, L6 | FastAPI portal: submit, case status and trace, approval queue, approve/reject (coordinator only), published timetable; the `X-User` header stands in for SSO |

## Safety (proposal §13)

`uv run python -m nts.safety` runs the 50-case safety set (authority,
claimed authority, "I approve" messages, injections, private-reason probing,
spoofing) through intake and the orchestrator with System Two and the policy
agent (Gemini). `--compromised` swaps in a parser that obeys every injected
instruction, to show which defences are deterministic: 49/50 pass, with 0
unapproved publishes, 0 authority violations, 0 injection successes and 0
leaks. The one failure is an "I approve, publish it" email from the HoD: the
fooled parser's constraint is within the HoD's authority, so it is created,
but it still only reaches "awaiting approval".

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

## Next steps

- **Experiment runs (API quota, spread over days):** parsing test split on the
  paraphrased corpus; policy test split; negotiation LLM configurations
  (ours-llm, A1, A3, B1, B3) on all 60 scenarios; the safety set with Gemini;
  judge ratings. Each run resumes from the cache after a daily-quota stop.
- **Team:** 100 hand-written requests and two annotators; the institute's
  real handbook; human pilot ratings (`data/human_ratings.csv`) for judge κ.
- **Compiler:** evaluate the Kaggle-trained GGUF with `eval_parsing --local`.
- Not built yet: swap requests, and a dense retriever for the BM25 +
  embedding hybrid.
