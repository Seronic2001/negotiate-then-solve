# Overview

**Negotiate, Then Solve** is a university timetabling service that takes change requests in plain language,
works out what they mean for the timetable, settles conflicts between people by negotiating over options a
constraint solver has verified, and publishes the result after a person approves it. Next to it, a chat answers
questions about the timetable ("am I free on Friday after lunch?", "which labs are free on Thursday?") from the
timetable itself, and takes requests in the same message.

This page is the map. [architecture.md](architecture.md) shows how the parts fit together; the other pages in
this folder go into each part.

## The problem

A published timetable keeps changing during the semester: a teacher is away for a conference, a lab is closed
for maintenance, a class needs a room with a projector, two teachers want to swap a slot. The requests arrive as
free text, through different channels, and they collide: when two of them cannot both be met, someone has to
concede, and there is usually no principled way of deciding who.

Two things make this hard for a language model alone:

- **Reading.** A request is vague ("my Monday class"), has implicit scope ("next week" or every week?), and
  often hides several requests in one message.
- **Deciding.** Whether a change fits is a combinatorial question over every class, room and person. A model
  that proposes options without checking them proposes options that break someone's hard constraint.

## The approach

The system splits the work so each part does what it is good at:

| Part | Does | Never does |
|---|---|---|
| Language models (fine-tuned, small) | Read messages into a small typed vocabulary: what is asked, about which class, when | Compute anything about the timetable |
| Code | Resolve names, dates and weeks; check every reading against the message and the timetable; answer questions from the timetable | Guess what a message means |
| Constraint solver (CP-SAT) | Decide whether a change fits, find the conflict when it doesn't, and produce every concrete repair | Choose between people |
| Negotiation | Offer only solver-verified repairs, ranked by priority tiers and a concession ledger, and explain them without leaking private reasons | Invent an option |
| People | Approve every change before it is published; decide escalations | |

**Research question.** Can solver-derived conflict sets constrain an LLM negotiator so that it resolves
infeasible requests with fewer rounds and less disruption than LLM-invented options, even when those options are
filtered by the same solver? When a request is infeasible, minimal unsatisfiable subsets (MUS) locate the
conflict, minimal correction sets (MCS) define the possible concessions, CP-SAT re-solves each into a concrete
timetable, and the negotiator may offer only these.

## Who uses it

Every person signs in with a role, and the role decides what they see (`web/world.py`, `VIEWS`; the endpoints
behind a view check it too).

| Role | What they do |
|---|---|
| Faculty, guest faculty, HOD | Ask about the timetable, send requests (cancel, move, swap, extra class, unavailability, preferences), answer negotiation messages, see their place in the concession ledger, give semester preferences |
| Student (class representative) | Ask about the timetable, report clashes, book rooms for club activities, give semester preferences |
| Timetable office (coordinator) | Approve or reject changes, roll back versions, manage policy documents and settings, build the semester timetable, watch health and experiments, run the human study |
| Dean | Decide escalations; see fairness |
| Lab in-charge, exam cell | Receive the messages and notices that concern them |

## Two ways in

1. **Requests**, from the portal's request builder, the chat, email or messaging. A request goes through the
   full pipeline: read, policy check, compile to constraints, solve, negotiate when it doesn't fit, audit for
   fairness, approve, publish. Each step is a state the request moves through (see
   [architecture.md](architecture.md#a-requests-life)).
2. **The chat**, on the home page beside the person's timetable. One message can hold several timetable
   questions, a request and a question about the rules ("when am I free on Friday, how many online classes are
   allowed, and move my DS lecture there"). The questions are answered from the timetable, the rule question
   from the handbook with citations, and the request goes into the pipeline, with "there" filled in from the
   answer. Follow-ups ("and Thursday?") are made to stand on their own from the conversation first. See
   [chat-lookups-memory.md](chat-lookups-memory.md).

## The models

One base model, **Qwen3.5-4B** (Q8_0 GGUF), served by `llama-server` with a LoRA adapter per task
(`adapters-lora.toml`). Each adapter learns one narrow job, so it can be small, retrained alone and measured
alone.

| Task | Adapter in use | Reads |
|---|---|---|
| `compile` | `nts-intents-v12-read-100` | A request into intents (17 kinds: unavailable, avoid, move, swap, cancel, extra class, load limit, club booking, …) |
| `policy`, `reply`, `explain` | `nts-read100` | A request against the handbook; a stakeholder's reply to a negotiation message; grounded explanations |
| `lookup` | `nts-lookup-v3` | A chat message into the timetable lookups it asks for (1 to 5 a message, 16 lookup tools) |
| `memory` | `nts-memory-v1` | A follow-up into a message that stands on its own, from the last messages of the chat |

Newer adapters are trained and evaluated but not switched on yet: `nts-lookup-v4` (the lookup vocabulary) and
`nts-memory-v1_1`. See [models-and-training.md](models-and-training.md).

Every model has a deterministic stand-in (a rule parser, a rule-based policy check, a regex question reader,
template explanations), so the app runs fully offline, and keeps running when the model server drops. Gemini can
replace the local model for every task (`--parser gemini`).

## Results at a glance

From the mid-submission report and the evaluation records in this repository; [evaluation.md](evaluation.md)
has the details and how each number is measured.

| What | Result |
|---|---|
| Negotiation, correct outcome (60 scenarios × 3 seeds) | **89.4%** against 75.6% for solver-filtered LLM options (B4, p = 4.6×10⁻⁶) and 83.3% for unverified ones (B3, p = 0.013); oracle gap 0.04 against 0.63 and 0.44; no invalid option offered |
| Reading requests (intents v12, test split) | 96.4% outcome match |
| Timetable questions (lookup v3, 362 questions) | 346/362 in the app's department; at least 346 and 343 in a department with shuffled names and one with shared courses it never saw |
| Long messages, 1–5 questions plus requests (200) | 140/200 whole messages right with lookup v4, against 111 with v3 |
| Follow-ups, memory then lookup (400 conversations) | 387/400 looked up right; 146/400 without memory |

## Two branches

This documentation covers the `finetuned` branch: the request pipeline, the fine-tuned readers, the chat and the
web app. The `agentic` branch takes a different route to the same problem: a tool-calling coordinator agent
(`src/nts`) handles a whole request over many turns, calling the solver and the timetable through about 30
tools, trained with SFT and then DPO. It is documented on its own branch.

## Where to read next

| Page | About |
|---|---|
| [architecture.md](architecture.md) | The layers, a request's life, the chat's path, models and fallbacks |
| [chat-lookups-memory.md](chat-lookups-memory.md) | Timetable questions, the lookup vocabulary, mixed messages, memory |
| [web-app.md](web-app.md) | The React front end and the API behind it |
| [models-and-training.md](models-and-training.md) | Adapters, serving, how training works, notebooks |
| [datasets.md](datasets.md) | Every dataset: what it is for, how it was made, its size |
| [evaluation.md](evaluation.md) | The main experiment, baselines, ablations, component benchmarks |
| [reading-requests.md](reading-requests.md) | System One, the intent vocabulary, checks, the rule parser |
| [policy.md](policy.md) | The policy agent and the handbook |
| [solving-and-negotiation.md](solving-and-negotiation.md) | CP-SAT, conflicts, the resolution ladder, fairness, the semester planner |
| [running.md](running.md) | Setup, the model server, configuration, tests |
| [limitations.md](limitations.md) | What is known not to work yet |

Deeper notes on single topics: [labelling](../labelling.md), [encoder intents](../encoder-intents.md),
[lookup classes](../lookup-classes.md), [regression matrix](../regression-matrix.md),
[improvement plan](../improvement-plan.md).
