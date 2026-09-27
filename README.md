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
uv run python -m evaluation.demo     # generate a department, solve it, run UC3
uv run nts-web                # web app on http://127.0.0.1:8000 (build the frontend first, see below)
```

## Layout

```
src/
  core/        the timetabling model: schemas, instances, CP-SAT solver, validator, conflicts (MUS/MCS), graph
  language/    LLM clients (Gemini, local), System One and Two parsing, the fine-tuned compiler and its data
  agents/      policy agent and policy documents, negotiation, priorities, concession ledger, explanations
  pipeline/    channels (ingest), the central store and the orchestrator (request lifecycle)
  semester/    course offerings -> semester timetable, plain-word preferences, versions, club bookings
  training/    multi-task training data for the local model (distilled from every agent-side call)
  evaluation/  benchmark, safety set, evaluation scripts, LLM judge, metrics and statistics
  web/         JSON API for the React app, the world behind it, the channel portal, semester endpoints
frontend/      React + TypeScript + Tailwind app (pages/, components/, lib/)
tests/         pytest, one file per area (`-m "not slow"` skips the department-size solves)
scripts/       one-off helpers (sample policy documents)
notebooks/     Kaggle notebooks: fine-tuning the local model, Unlimited-OCR sidecars
data/          handbook, request corpora, policy documents, training data
course-offering/  the institute's course offering document and reference timetables
runs/          outputs: LLM cache, experiment results, semester state (not committed)
```

Dependencies run one way: `core` <- `language` <- `agents` <- `pipeline`, `semester`; `training`, `evaluation` and `web` sit on top.

| Module | Proposal | What it does |
|---|---|---|
| `src/core/schemas.py` | §7.4, Fig. 2 | `Constraint`, `Request` + lifecycle state machine, `Placement`, `TimetableVersion`, `ConcessionEntry` |
| `src/core/instance.py` | §1, §8.3 | Rooms, faculty, groups, sessions, calendar; institute policy as Tier 1 constraints |
| `src/core/semantics.py` | §8.3 | What each constraint type means for a placement (shared by solver and validator) |
| `src/core/solver.py` | §8.3–8.4 | CP-SAT model; `a_k ⇒ C_k` guards; full build, minimal-change repair, lexicographic tiers |
| `src/core/conflicts.py` | §8.5 | `find_mus` (deletion-based shrinking), `enumerate_mcs` (cheapest-first, solver-verified witnesses) |
| `src/core/validator.py` | §8.2 step 4, §12.4 | Rejects bad compiled constraints; scores any timetable's hard-constraint validity |
| `src/core/generator.py` | §12.1 | Seeded synthetic departments (30 faculty, 60 course sections, 20 rooms by default) |
| `src/core/scenarios.py` | §9 | UC3 lab-contention fixture (the benchmark generalises it) |
| `src/core/itc.py` | §12.1 | ITC-2007 Track 3 `.ctt` loader and `.sol` writer |
| `src/language/corpus.py` | §12.1 | Request corpus generator with labels; JSONL load/save |

## Parsing layer and Gemini

Put one or more keys in `.env` (git-ignored):

```sh
# Single key or comma-separated list of keys:
GEMINI_API_KEY=key1,key2,key3
# Or explicitly via GEMINI_API_KEYS:
# GEMINI_API_KEYS=key1,key2,key3
# Or numbered:
# GEMINI_API_KEY_1=...
# GEMINI_API_KEY_2=...

# optional overrides (defaults are pinned in src/language/llm.py)
GEMINI_MODEL=gemini-3.5-flash-lite       # agent: System Two parser, negotiator
GEMINI_SIM_MODEL=gemini-3.1-flash-lite   # stakeholder simulators, LLM judge
GEMINI_FLASH_MODEL=gemini-3.8-flash      # larger-model comparison set
GEMINI_RPM=15     # requests per minute per key
GEMINI_RPD=500    # requests per day per key
```

**API Key Pooling & Load Balancing**: When multiple keys are configured, `src/language/llm.py`
pools them automatically with round-robin load balancing. Having $N$ keys multiplies
your total throughput ($N \times \text{RPM}$) and daily capacity ($N \times \text{RPD}$).
If an individual key hits a per-minute rate limit or reaches its daily quota, the
client dynamically rotates and fails over to the next available key in the pool.

`src/language/llm.py` caches every response under `runs/llm_cache/` (keyed by model,
prompts, schema and temperature), so rerunning an experiment costs no quota,
and a run stopped by the daily budget resumes the next day where it stopped.

| Module | Proposal | What it does |
|---|---|---|
| `src/language/llm.py` | §14 | Gemini client: structured output, cache, RPM limiter, daily budget, 429 backoff |
| `src/language/parsing.py` | §8.2 | System Two parser. The LLM drafts; tiers (Table 5), authority and validation are deterministic |
| `src/language/system_one.py` | §8.2 | Calibrated TF-IDF + logistic regression: request type, action, confidence, fast-path routing with τ |
| `src/evaluation/metrics.py` | Table 11 | ECE, constraint exact match, atom-level P/R/F1 |
| `src/evaluation/parsing.py` | §12 | `uv run python -m evaluation.parsing --limit 40` |
| `src/language/paraphrase.py` | §12.1 | Rewrites the corpus in varied registers with the simulator model; a rule-based check rejects paraphrases that change days, numbers or names |

**Paraphrased corpus.** `uv run python -m language.paraphrase` writes
`data/requests-para.jsonl`: the same 600 requests and labels, with each text
rewritten (10 per call, about 60 calls) and the template kept in
`template_text`. Injected instructions are cut off before paraphrasing and put
back verbatim. Paraphrases that change a day, number, person, room, group or
course are retried in another style. The check cannot see a wish turning into
a demand, so read a sample by hand. Evaluate on it with
`--corpus data/requests-para.jsonl`; add `--s1-train data/requests.jsonl` to
train System One on templates and test it on paraphrases.

## Policy agent

`src/agents/policy.py` checks a parsed request against the handbook
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

`uv run python -m evaluation.policy --split val` scores allow/deny accuracy,
citations, make-up obligations and retrieval recall against the corpus
`rules` labels. Use `--policy-model gemini-3.1-flash-lite` for development
when the agent model's daily quota is spent.

| Module | Proposal | What it does |
|---|---|---|
| `src/agents/policy.py` | L3, UC2, UC4 | Handbook loader, BM25, policy agent with citation checks |
| `src/agents/documents.py` | L3 | Policy documents in any form: PDF, scans, photos, HTML, Markdown → rules with provenance |
| `src/evaluation/policy.py` | Table 11 (RAG) | Parse-then-policy evaluation |

### Policy documents: PDF, HTML, scans and photos

Institutes publish regulations as PDFs, circulars as scans, notices as photos
and pages on their website. `src/agents/documents.py` turns all of them into rules the
policy agent can retrieve and cite, next to the handbook:

| Input | How it is read |
|---|---|
| PDF with a text layer | the text layer, page by page (pypdfium2); running headers, footers and page numbers are dropped |
| scanned PDF page (no text layer) | rendered at 220 dpi, then OCR |
| image (scan, phone photo) | OCR, after deskewing the detected text boxes |
| HTML page | the content only: scripts, navigation, header, footer, cookie banners and side panels are removed; headings, lists and table rows kept |
| Markdown / text | as written; the handbook keeps its `[RULE-ID]` headings |

OCR backends (`NTS_OCR`):

- `rapidocr` (default, CPU): PaddleOCR's PP-OCR text detector and English
  recogniser as ONNX. The English model (9 MB) is downloaded to
  `runs/ocr_models/` on first use (the bundled model drops the spaces between
  English words). Lines read with low confidence get a second look at a larger
  detection size. About 3–7 s per page on the laptop CPU.
- `unlimited`: [Baidu Unlimited-OCR](https://huggingface.co/baidu/Unlimited-OCR)
  (3B, 0.5B active, MIT), a document-parsing model that returns Markdown. It
  needs about 8 GB of VRAM, so it does not run on the development laptop.
  Either serve it with vLLM on a GPU machine and set `NTS_OCR_URL`, or run
  `notebooks/unlimited_ocr_kaggle.ipynb` on a Kaggle T4. The notebook writes a
  `<file>.ocr.json` per document; put it next to the file and it is used for
  every page without a text layer.

OCR results are cached by image hash (`runs/ocr_cache/`). The text is then cut
into rules at numbered headings ("3.2 Timetable changes", "2. Capacity. …",
including OCR slips such as "1.Fixed"); a document without headings becomes
paragraph chunks. Each rule records its file, pages and method, and gets the
ID `<DOC>-<number>` (`EXAM-3.2`) unless the document gives its own `[ID]`.

```sh
uv run python -m agents.documents                        # ingest data/policies/ and run demo queries
uv run python -m agents.documents notice.jpg --show-text # one file, with the OCR text
uv run python scripts/make_policy_samples.py          # rebuild the four sample documents (needs Chrome)
```

`data/policies/` holds one sample of each kind (a digital PDF, a scanned PDF,
a photographed notice and a web page); the web app loads them at start-up. On
the Handbook page the coordinator can add or remove documents, and every rule
and search hit shows the document, page and method it came from.

Known limits: OCR can misread single letters ("ciasses"), which the confidence
shown per document hints at. BM25 matches words, not meanings: "shift my
practical to another lab" does not reach "moved into a different laboratory"
(the dense half of the proposal's hybrid retriever is not built).

## Fine-tuned compiler (local model)

`uv run python -m language.compiler` writes `data/compiler/{train,val,test}.jsonl`:
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
uv run python -m evaluation.parsing --local --corpus data/requests-para.jsonl --split val --limit 100 --workers 1
```

`src/language/local.py` talks to any OpenAI-compatible server (llama.cpp, Ollama, LM
Studio), constrains output to the JSON schema, keeps thinking off and caches
like the Gemini client. On a GPU with less memory than the model file, lower
`-ngl` so some layers run on the CPU.

### Multi-task local model (every agent-side call)

The compiler only parses. `src/training/distill.py` builds data for the other calls
the deployed system makes: reading negotiation replies, grounded explanations
and the policy agent. Each example uses the system prompt and user message the
system sends at run time (the same code builds them), so the trained model
drops into every `--local` path unchanged. The stakeholder simulators, the
judge, the paraphraser and the LLM baselines (A1, A3, B1, B3) stay on Gemini:
they test or grade the system, or measure an untuned LLM.

```sh
uv run python -m training.distill messages --seeds 1-10   # negotiations on new scenarios; no API (~30 min)
uv run python -m training.distill reply                   # simulator model voices accept/counter/reject replies
uv run python -m training.distill explain                 # agent model as teacher
uv run python -m training.distill policy                  # agent model as teacher
uv run python -m training.distill export                  # data/multitask/{train,val}.jsonl, ≤800 per task
```

- **Scenarios** come from benchmark seeds 1-10; seed 0 (the evaluation set) is
  refused, and the last seed is the validation split.
- **Replies:** the decision is drawn first (accept a random option, counter
  with a window, reject), then the simulator model (or `--voice template`,
  no API) writes the text, so labels are exact.
- **Explanations:** a teacher output is kept only if every claim cites known
  fact IDs (brackets stripped) and passes the claim checker, every option is
  cited, and nothing private leaks. The stage prints why the rest were dropped.
- **Policy:** input parses come from the rule parser (no API). The verdict and
  citations must match the corpus label and cite only rules that were shown.
  The make-up obligation, which the teacher often leaves out, is set from the
  label.

Every stage caches, so one stopped by the daily quota resumes when run again.
Train with `notebooks/train_compiler_kaggle.ipynb` on the `data/multitask/`
folder (it reports validation per task), then score the model with
`eval_parsing --local`, `eval_policy --local` and `eval_negotiation --local`.

## Data

`uv run python -m language.corpus` regenerates `data/requests.jsonl` (600 requests,
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
`core.itc.load_ctt(Path("comp01.ctt"))`. Room capacity is soft by default,
as in ITC; the ITC soft constraints for working days, compactness and room
stability are not modelled.

## Interpretation layer (L5): negotiation

| Module | Proposal | What it does |
|---|---|---|
| `src/agents/priority.py` | §8.4 | π_k = auth + impact + justification + lead + credit − disruption; option cost = Σπ + λ1·moved + λ2·ΔGini; `flat=True` for ablation A2 |
| `src/agents/ledger.py` | §8.6 | Concession ledger with semester decay; Gini coefficient |
| `src/agents/explainer.py` | §8.7 | Conflict → numbered facts (MUS constraints, rules, rooms, options, ledger). Template, grounded (claims cite facts; a checker drops claims whose days, numbers or names are not in the cited facts) and free (A3) modes; private-reason leak check |
| `src/agents/negotiation.py` | §8.6 | Resolution ladder: auto-substitute → auto-relax (notices) → negotiate over MCS options (2–3 solver-verified alternatives per message, cheapest owner first, lowest credit on ties, one extra probe after a refusal) → escalate with a brief. Replies: accept / counter / reject / no reply |
| `src/agents/simulators.py` | §12.1 | Stakeholders with hidden flexibility (acceptable windows, room flexibility, whether they volunteer it, whether they reply); scripted or LLM-voiced replies |
| `src/evaluation/benchmark.py` | §12.1 | 60 scenarios: contention, substitute, deadlock, Tier 3 vs 4 squeeze, capacity shortfall, preference trade-off, policy; the oracle (B4) tries every hidden-flexibility combination |
| `src/evaluation/negotiation.py` | §12.2–12.5 | Runs ours / A1–A3 / B1–B4; validity, correct outcome, rounds, cost vs oracle, escalation P/R, concession Gini, faithfulness, leaks; McNemar, Wilcoxon, bootstrap CIs |
| `src/evaluation/judge.py`, `src/evaluation/stats.py` | §12.5 | Batched LLM judge (clarity, acceptability) and quadratic-weighted Cohen's κ against human raters |

```sh
uv run python -m evaluation.benchmark                                  # data/scenarios.jsonl (about 30 s)
uv run python -m evaluation.negotiation --offline                 # ours, A2, B2, B4: no API calls (about 6 min)
uv run python -m evaluation.negotiation --configs ours-llm,A1,A3,B1,B3   # Gemini; spread over days
uv run python -m evaluation.judge runs/negotiation-XXXX.json           # LLM judge (batched, Flash-Lite)
uv run python -m evaluation.judge --kappa data/human_ratings.csv       # judge vs human raters
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
| `src/pipeline/orchestrator.py` | Fig. 2, §8.9 | The request lifecycle end to end; System One routing; refusal, denial, clarification, escalation, answer and forward exits; fairness audit; publishing only through `approve()` by a listed approver; notifications to affected people only |
| `src/pipeline/store.py` | L1, state | SQLite: requests (with dedupe), constraint records, timetable versions (per week, with rollback), ledger, audit log |
| `src/core/graph.py` | §8.8 | NetworkX knowledge graph: owns, references, has_authority_over, reports_to, derived_from, conflicts_with, affects, balance |
| `src/pipeline/ingest.py` | L0 | Email (RFC 822, IMAP poller), messaging (Slack-shaped JSON) and portal adapters; email → person → role; unknown senders rejected; quoted replies stripped; threading |
| `src/web/portal.py` | L0, L6 | FastAPI portal: submit, case status and trace, approval queue, approve/reject (coordinator only), published timetable; the `X-User` header stands in for SSO |
| `src/web/world.py` | all | The demo department and the real pipeline behind the web app; inboxes for interactive negotiation; which views each role sees |
| `src/web/app.py` | all | JSON API for the React front end (`uv run nts-web`) |
| `src/language/rule_parser.py` | L2 | Offline rule-based parser (same output and post-processing as System Two) |
| `frontend/` | L0, L6 | React 19 + TypeScript + Tailwind 4 + Framer Motion; Recharts, d3-force |

## Safety (proposal §13)

`uv run python -m evaluation.safety` runs the 50-case safety set (authority,
claimed authority, "I approve" messages, injections, private-reason probing,
spoofing) through intake and the orchestrator with System Two and the policy
agent (Gemini). `--compromised` swaps in a parser that obeys every injected
instruction, to show which defences are deterministic: 49/50 pass, with 0
unapproved publishes, 0 authority violations, 0 injection successes and 0
leaks. The one failure is an "I approve, publish it" email from the HoD: the
fooled parser's constraint is within the HoD's authority, so it is created,
but it still only reaches "awaiting approval".

## Semester timetable from the course offering document

The timetable office builds the whole semester from the institute's course
offering document, collects preferences from faculty and students, publishes,
and then re-solves around changes during the semester. Students book club
activities in the evenings, checked automatically against it.

| Module | What it does |
|---|---|
| `src/semester/offerings.py` | Reads the course offering document into courses (code, name, L-T-P-C, H1/H2/H, enrolment cap, faculty), programmes (required courses, elective slots) and elective pools. PDFs are read by position, so wrapped cells stay with their row; scans and web pages go through `agents.documents` |
| `src/semester/solver.py` | The institute's week, 40 rooms, sessions from L-T-P, the two-phase CP-SAT solver and an independent check of every hard rule |
| `src/semester/requests.py` | Preferences, unavailability and room closures in plain words |
| `src/semester/service.py` | Saved state, background builds, versions with diffs, publishing, club bookings |
| `src/semester/clubs.py` | Club activity checks and alternatives |
| `src/web/semester.py` | The endpoints (mounted by `web.app`) |

**The week** (from the institute's lecture and tutorial timetables): six
lecture slots of 1 h 25 min (08:30, 10:05, 11:40, 14:00, 15:35, 17:10); Mon, Tue
and Wed are days A, B and C, repeated on Thu, Fri and Sat; tutorials on a
one-hour grid (09:00 … 20:00); labs of up to three hours from 09:00 or 14:00;
Wednesday and Saturday afternoons free. All of it is in `SemesterCalendar`.

**Sessions from L-T-P and the course code:**

- L ≥ 3: a lecture pair (the same slot on a day and the day three later);
  L = 1–2 or "(H)": one lecture a week. A course bigger than the largest hall
  runs parallel sections, as many as the halls allow.
- T > 0: a tutorial hour, all groups (≤ 80 students) in parallel rooms.
- P > 0: a lab block of min(P, 3) hours in the lab type of the course's area
  (CS → computing labs, EC → electronics, SC → science, PD → design studio;
  names such as "Embedded" or "Signal" also mean electronics). Batches are
  made of whole programmes, so each programme is busy only in its own batch.
- Honours projects, theses, seminars and PE Centre sports are listed but not timetabled.

**Rooms:** 40 by default (3 halls of 250–300, 27 lecture rooms of 40–150,
5 computing labs, 3 electronics labs, a science lab and a design studio),
named as in the institute's timetables; `default_rooms()`. Programme sizes
are estimates the office corrects before building.

**The solver.** Phase 1 (CP-SAT) chooses a time for every session. Hard: no
programme, faculty member or room type double-booked, checked per half of
the semester (an H1 and an H2 course may share a slot), room demand within
supply at every capacity, the free afternoons, hard preferences. Soft:
preferences, electives of one pool kept apart, no evening lectures for first
and second years, no late tutorials, at most two lectures a day per
programme; in a repair, every move costs more than any preference. Phase 2
gives each session its rooms (smallest that fits; the same rooms as before in
a repair). `verify()` then re-checks every hard rule on the result.

On the Monsoon 2026 offerings (150 courses, 40 programmes, 18 pools →
280 sessions, 410 weekly meetings) a build takes about a minute on the
laptop and breaks no hard rule, with no two electives of a pool clashing;
a change such as "SH1 closed on Mondays" re-solves in about ten seconds and
moves only the sessions that have to move.

**Club activities** are checked for club hours (weekday evenings, the free
afternoons), notice (two days; five working days for the auditorium), the
members' programmes being free, and a free lecture room big enough (picked
automatically if none is named). Events over 150 people and the auditorium
go to the office. A request that fails comes back with alternatives that pass,
and the booking rules from the policy documents are cited.

```sh
uv run python -m semester.offerings course-offering/CourseOfferings-M26-V7.pdf --all   # what was read
```

In the web app: **Build timetable** (office: offerings → preferences →
timetable → changes), **Semester preferences** (faculty and class
representatives) and **Club activities** (students; the office approves the
large ones). State is saved in `runs/semester/` (`NTS_SEMESTER_DIR`); the build
time limit is `NTS_SEMESTER_TIME` (default 60 s).

Not modelled: which electives each student actually takes (electives are
only kept apart within a pool), rooms' distance between back-to-back classes,
and the demo personas are not the institute's faculty (preferences name the
faculty member in the text).

## Web app (React + TypeScript front end, FastAPI back end)

```sh
cd frontend && npm install && npm run build && cd ..
uv run nts-web                       # API + built UI on http://127.0.0.1:8000
NTS_PARSER=gemini uv run nts-web     # System Two + policy agent on Gemini instead of offline rules
NTS_PARSER=local uv run nts-web      # System Two on the fine-tuned compiler (llama-server; NTS_LOCAL_URL, default http://localhost:8080/v1)

cd frontend && npm run dev           # hot-reloading UI on :5173, /api proxied to :8000
```

`src/web/app.py` runs the real pipeline on a demo CSE department (8 faculty, 56
sessions) and replays a short history at start-up through it: a conference
absence, preferences, a lab contention that is negotiated, a student's
injection attempt (refused), a lunch-slot request (denied with a citation), a
vague request (clarification), a policy question (answered) and a lab outage
that only Tier 0-2 changes could fix (escalated). Requests run in background
threads and the UI follows them through the event log.

- **Auth is mocked.** Sign in by picking a person; the client sends `X-User`.
  Every permission is enforced server-side (only the coordinator approves,
  people see their own cases, replies only from the addressee). `?as=F-101`
  on any URL signs in directly, for demos and screenshots.
- **Negotiation is interactive.** When the negotiator needs someone's answer,
  the message waits in that person's inbox (accept an option, counter with
  days and times, or decline). "Let the simulator answer" and per-person
  autopilot let one person demo both sides; unanswered messages escalate at
  the deadline (`NTS_REPLY_DEADLINE`, default 900 s).
- **Offline by default.** Without an API key, `src/language/rule_parser.py` (a
  rule-based stand-in for System Two: 94% action accuracy and 83% compiled
  constraints on the paraphrased test split, vs Gemini's 100% on validation)
  and `RulePolicyAgent` (real BM25 retrieval, rule-based verdicts) keep every
  downstream layer real.
- A newer request from the same person replaces their earlier constraint on
  the same class ("superseded"), instead of negotiating with themselves.
- The web negotiator disables CP-SAT presolve (it is about 2 of 3 seconds per
  feasibility check at this size) and ranks correction sets before computing
  alternatives, so a negotiation round takes about 15-20 s and a direct repair
  about 3 s. The research runs keep the defaults.

Views: sign-in (persona picker), overview with live activity, new request
with a live lifecycle, requests, case audit (routing, parse, policy with
retrieved/cited rules, the MUS per round, the negotiation thread, claim-to-fact
explanation grounding, diff, fairness, event trace), negotiation inbox,
approvals (coordinator), timetable with versions and rollback, fairness
ledger, handbook with a retrieval playground, how decisions work (tiers,
weights, ladder, safety rules), knowledge graph, observability (LLM quota,
stage latency, routing, faithfulness, safety counters, event stream) and
experiments (results from `runs/`). Dark and light themes; Ctrl+K palette.

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
- **Local model:** generate the multi-task data (`training.distill`), train it, and score it with the `--local` evaluations.
- Not built yet: swap requests, and a dense retriever for the BM25 +
  embedding hybrid.
