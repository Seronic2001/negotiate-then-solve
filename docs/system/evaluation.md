# Evaluation

How every part of the system is measured, what it is compared against, and what the results are. The main
experiment answers the research question; the component benchmarks check each part on its own. The datasets
behind them are described in [datasets.md](datasets.md).

All results come from the evaluation records in this repository and the mid-submission report. Every model answer
is cached, so any table can be scored again without calling a model.

## The main experiment: does solver-grounded negotiation work?

### The question

When two requests can't both be met, someone has to give way. We compare two ways of finding the options to
offer people:

- **Ours**: the solver finds the options. It locates the conflict (a minimal unsatisfiable subset, MUS), lists
  every minimal way of resolving it (minimal correction sets, MCS), and re-solves each into a full, concrete
  timetable. The language model only explains these options and reads people's replies; it can't invent one.
- **The usual way**: a language model invents the options, with or without the solver checking them afterwards.

### The hypotheses

| | Hypothesis, in plain words |
|---|---|
| **H1** | Options a model invents cost extra: many are impossible, and filtering them costs extra model calls and rounds |
| **H2** | Our way settles conflicts at least as often as filtered invention, with fewer rounds, less disruption, and an outcome closer to the best possible one |
| **H3** | Explanations built only from the solver's facts are more faithful and never leak a private reason |
| **H4** | Keeping a ledger of who gave way before spreads the burden more evenly than treating everyone the same |

### The setup

- **60 scenarios**, each with a planted conflict of one of 7 kinds and hidden flexibility for each person
  (see [datasets.md](datasets.md#negotiation-scenarios-the-main-experiment)).
- **Simulated people.** Each person is played by a simulator that answers according to their hidden profile, in
  one of four styles: strict, flexible, cost-sensitive or history-sensitive.
- **An oracle.** The solver, given everyone's hidden flexibility, finds the best possible outcome. "Correct" means
  a run ends the way the oracle says it should (agreed, or escalated when no agreement is possible).
- **A fair fight on language.** Ours uses the small fine-tuned Qwen3.5-4B; the baselines use the much larger
  Gemini 3.5 Flash-Lite, so they are not held back on writing.
- **Repeats.** Ours, B3 and B4 run all 60 scenarios with 3 seeds: 180 paired runs each. The ablations run a
  stratified 30, B1 a stratified 20, and B2 and the oracle all 60 (they use no model). That is 650 model runs
  instead of the 5,040 a full grid would need.
- **One ledger per run.** Scenarios run in order with one concession ledger, so fairness builds up over a
  "semester" of conflicts among the same people.

### What is compared

| Configuration | What it does | Why it is there |
|---|---|---|
| **Ours** | Solver-verified options (MCS, re-solved), ranked by priority tiers and the ledger; grounded explanations; replies read as tool calls | The system under test |
| **B1** LLM only | The model writes the timetable directly; no solver | Can a model just do it? (Control) |
| **B2** Solver only | The same solver and priorities as ours, but the cheapest repair is imposed without asking anyone | Is negotiation needed, or only a solver? (Control) |
| **B3** Unverified | Like ours, but the model invents the options and they are offered unchecked | How often are invented options impossible? |
| **B4** Filtered | Like B3, but the solver throws out impossible options and the model tries again (up to 3 calls a round) | **The main baseline**: the strongest version of "the model invents" |
| **Oracle** | The solver with everyone's hidden flexibility | The upper bound |

### Metrics

| Metric | Meaning |
|---|---|
| Correct outcome | The run ends as the oracle's does |
| Agreement | The run ends in an agreement (not an escalation) |
| Rounds | Rounds of messages before it ends |
| Oracle gap | How much worse the final timetable is than the oracle's (lower is better) |
| Invalid options | Options offered that are impossible |

### Results

| System | Runs | Correct outcome | Agreement | Rounds | Oracle gap | Invalid options |
|---|---|---|---|---|---|---|
| B1 LLM only | 20 | 0.0% | 0.0% | – | – | 80% of timetables broken |
| B2 Solver only | 60 | 31.7% | 0.0% | – | 0.131 | – |
| B3 Unverified | 180 | 83.3% | 66.7% | 1.47 | 0.443 | 51.0% of options |
| B4 Filtered | 180 | 75.6% | 51.1% | 1.48 | 0.628 | 5.7 filtered per scenario |
| **Ours** | 180 | **89.4%** | **78.9%** | **1.38** | **0.041** | **0** |

Statistical tests (McNemar on correct outcome): ours against B4, p = 4.6×10⁻⁶; ours against B3, p = 0.013. The
differences in rounds are not significant.

**What this means, in plain words:**

- A model writing the timetable itself (B1) breaks it every time.
- A solver alone (B2) finds a valid repair but imposes it, so it is right only a third of the time: people's
  hidden flexibility matters, so negotiation is needed.
- When the model invents options (B3), half of them are impossible.
- Filtering them (B4) makes things **worse**, not better: the solver rejects most inventions, and the survivors
  are fewer and worse options, so fewer people agree.
- Ours offers only options that work, gets the right outcome 89% of the time, and its final timetables are
  almost as good as the oracle's (gap 0.04 against 0.63 for B4).

### Ablations: which part matters?

An ablation takes our system and removes or replaces one part, to see what that part does.

| Ablation | What is changed | Tests | Result |
|---|---|---|---|
| **A1** Flat weights | No priority tiers and no ledger: everyone counts the same | H4 | The same resolution (90.0%); burden spread (Gini) 0.224 against the ledger's 0.241 |
| **A2** Free-text explanations | The model writes explanations freely instead of from the solver's facts | H3 | The same resolution; **12 private reasons leaked**, against 0 with grounded explanations |
| **A3** Regex replies | A keyword reader turns replies into actions instead of the model's tool calls | Reply reading | The same resolution: the simulators' replies are plain enough for keywords; real replies are more varied, which the reply benchmark below measures |

**What this means:** the three parts don't change how often conflicts get settled in these scenarios. They change
what people see. Grounded explanations never leak a private reason (H3). The ledger did not spread the burden more
evenly yet (H4 not supported), because each scenario has only one conflict, which gives the ledger little to act
on; scenarios with a sequence of requests are the planned test.

### The hypotheses, now

| | Verdict | Evidence |
|---|---|---|
| H1 | Supported (except rounds) | 51% of invented options are impossible; B4 needs 3.97 model calls per scenario and still agrees least |
| H2 | Supported (except rounds) | 89.4% against 75.6% correct; oracle gap 0.04 against 0.63; rounds equal within the confidence interval |
| H3 | Partly | 0 against 12 private-reason leaks; claim faithfulness 0.98, not yet checked by people |
| H4 | Not supported yet | Gini 0.241 against 0.224; one conflict per scenario |

### Where ours fails

19 of 180 runs. Every one is a **safe** escalation where the oracle found an agreement: a person didn't reply in
time (11), or the option they would accept was not among those offered (8). No run ever offered an impossible
timetable.

## Component benchmarks

### Reading requests

**Compiling to constraints** (151 test requests):

| Reader | Exact compile | Atom F1 | Action accuracy |
|---|---|---|---|
| Gemini 3.5 Flash-Lite (prompted) | 92.4% | 0.977 | 99.3% |
| Qwen3.5-2B + LoRA | **97.8%** | **0.996** | 96.5% |
| Qwen3.5-4B + LoRA | **97.8%** | **0.996** | **99.3%** |

Both small fine-tuned models beat the large prompted one; the 4B one also decides what to do with a message as
well as Gemini.

**The intent reader**, scored by **outcome match**: does the reading lead to the same change to the timetable as
the correct reading? A different wording that does the same thing counts as right. **Silent wrong** is a reading
that changes the timetable wrongly without asking, the worst kind of mistake.

| Reader | Test (417) | With typos | Compositional | Relations |
|---|---|---|---|---|
| Rule parser (baseline) | 51.6% / 21.1% wrong | 38.6 / 24.9 | 50.0 / 28.6 | 0.0 / 5.0 |
| Intents v11 | 95.4 / 2.4 | 94.2 / 3.1 | 78.6 / 14.3 | 45.0 / 0 |
| **Intents v12** (after epoch 2) | **98.1 / 1.9** | **97.6 / 1.9** | **85.7 / 0.0** | **77.5 / 0** |

The adapter in use is v12 after its third epoch (`read-100`): 96.4% on the test split. The second epoch is
better on the common requests and the third on the newest, smallest skills (see
[improvement-plan.md](../improvement-plan.md)). Per held-out suite, and v13 against v12, see [regression-matrix.md](../regression-matrix.md). Robustness to
typos and chat shorthand: `evaluation/robustness.py`.

### The policy check

| | Allow/deny accuracy | Deny recall (rule cited) | Make-up obligation recall |
|---|---|---|---|
| Gemini 3.5 Flash-Lite | 98% | 0.80 | 0.21 |
| **Qwen3.5-4B + LoRA** | **99%** | **0.90** | **1.00** |

The fine-tuned model learned the make-up class rule that the prompted model misses. **Retrieval** over the
handbook and documents reaches recall@5 of 0.93 with hybrid search; word matching (BM25) is best on the raw
messages and dense search on reworded ones (`evaluation/retrieval.py`).

### Replies and safety

| Reply reader (100 replies) | Right tool | Right arguments | Unsafe actions |
|---|---|---|---|
| Qwen3.5-4B base (prompted) | 65% | 100% | 0 |
| Gemini 3.5 Flash-Lite | **100%** | 85.5% | 0 |
| **Qwen3.5-4B + LoRA** | **100%** | **100%** | 0 |

**Safety set** (48 cases through the real pipeline): every case handled safely. No unapproved publish, no change
made without authority, no injection obeyed, no private reason revealed, and no case changed the published
timetable.

### Timetable questions, mixed messages and follow-ups

Scored by what each reading resolves to (the lookup and its arguments, after the code resolves names and weeks),
not by its wording. Full tables in [chat-lookups-memory.md](chat-lookups-memory.md#results).

| Test | Baseline | Best |
|---|---|---|
| Single questions, set A (362) | Regex 242, Gemini 320 | v2 347, v3 346 |
| The same in unseen departments (C, D) | v1 329, 327 | v3 at least 346, 343 |
| Long and mixed messages, whole message right (200) | v3 111 | **v4 140** |
| Requests found in mixed messages (123) | v3 112 | **v4 122** |
| Chat: question and request in one message (26) | 8 before the change | **v4 26** |
| Follow-ups, memory then lookup (400) | 146 without memory | **388** (memory v1 + lookup v4) |

**How they are built** (in plain words):

- **Test sets A–D** fill 142 test templates three times each, in four kinds of department, so a model that only
  memorised names fails C and D.
- **Long messages** join 1 to 5 test questions with requests and rule questions, sometimes in ways training never
  uses.
- **Chat cases** (`before_after/`) are sent through the real app, as a teacher, with the chat emptied before each,
  and checked for what came back: the lookups, a request, a rule answer, the words in the request.
- **End to end** passes each of memory's 400 test conversations through memory and then the lookup adapter, and
  checks that the rewrite is looked up the same way as the correct rewrite would be.

## Other measures

- **The judge** (`evaluation/judge.py`): a language model rates negotiation messages (clarity, acceptability),
  to be checked against people's ratings (Cohen's κ).
- **The human study** (`evaluation/study.py`, the Human study page): two team raters per item, participant codes,
  and a pilot with faculty after ethics clearance.
- **Smoke test** (`evaluation/smoke.py`): 12 everyday requests through the whole web app, each checked against what
  should happen.
- **System One** (`evaluation/system_one.py`): every classifier for routing messages, on every test set.

## Running the evaluations

| Script | Measures |
|---|---|
| `python -m evaluation.negotiation --plan --local --sim-local` | The main experiment, every configuration |
| `python -m evaluation.negotiation --offline` | The same with no model calls |
| `python -m evaluation.parsing`, `evaluation.intents`, `evaluation.suites` | Reading requests |
| `python -m evaluation.policy`, `evaluation.retrieval` | The policy check, retrieval |
| `python -m evaluation.replies`, `evaluation.safety` | Replies, the safety set |
| `python -m evaluation.lookup_set --local URL --adapter nts-lookup-v3` | Test set A (`--shuffle` for C, `--department 8 --shared` for D) |
| `python -m evaluation.lookup_set --multi ...` | Long and mixed messages |
| `python -m evaluation.memory_set --test`, `evaluation.end_to_end` | Memory, then end to end |
| `python before_after/run.py before_after/phase_1 --out after` | Chat cases through the app |

Every model answer is cached by model and prompt, so a run stopped by a network drop or a quota continues where it
stopped, and any result can be scored again for free.
