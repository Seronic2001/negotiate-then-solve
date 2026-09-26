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
  rule-breaking and prompt-injection cases.

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

- Weeks 3–4 (remaining): LLM paraphrasing of the corpus (`Paraphraser` hook);
  100 hand-written requests checked by two annotators; swap requests.
- Weeks 5–6: parsing layer (System One routing, QLoRA compiler, Gemini Flash System Two); policy RAG.
- Weeks 7–8: priority scores π_k, resolution ladder, concession ledger, grounded explainer.
