# Limitations

What is known not to work yet, why, and what would fix it. Each item was found by a test or by trying it in the
app; none is a guess.

## Timetable questions

| Gap | Example | What happens | Why | Fix |
|---|---|---|---|---|
| **Time ranges** | "am I free between 10 and 2 on Monday?", "after 2 pm", "before 11" | Read as the two ends only ("free at 10 am and 2 pm"), or the reading is rejected and the regex answers | No training row, in any version, asks about a range of times; the v4 vocabulary can say it (`after`, `before`) but was never shown how | Training rows for "between X and Y", "from X to Y", "after X", "before X", "X–Y pm"; a range test set |
| **Date ranges** | "am I free between 9 Nov and 13 Nov?" | Read as the first and last day only | The same: no rows | The same rows, with dates |
| **"In week N"** (v4) | "my free slots in week 2" | Read as week 1 | v4's new rows never say "in week N"; v3 knew it from older data, and v4 forgot it | A v4.1 top-up from v4's adapter with these rows and more replay |
| **Requests read as questions** (v4) | "can I have Thursday free?", "can I book Room 102 on 7 Aug?" | Looked up (the request card is still offered, from the request words) | Not in v4's new rows | v4.1: a lookup **and** a request part for these |
| **Private reasons** (v4) | "why was Dr. Rao's class cancelled?" | Looked up as changes, not kept private | Not in v4's new rows | v4.1 rows: "why …" is `unanswerable` |
| **"Who else teaches X and is free"** (v4) | | Read as free hours of the course's teachers | Not in v4's new rows | v4.1 rows |
| **Course "me"** (v4) | "somebody free at 10 am who could take my class?" | "I don't know a course called 'me'" | The model writes `course: "me"` | A check that drops a course made only of ordinary words |

The first two hold for every lookup adapter. The v4 ones are why v4, though clearly better on mixed and long
messages, is 6–10 questions behind v3 on single questions; they are the same few kinds in every department, so
they are forgotten, not memorised. The test labels also lag behind in two places: "how many teaching hours does X
have?" does not yet accept the `counts` tool, and "is it possible to shift my class to Monday?" does not accept
`move_options`, though both readings are right.

## Requests

| Gap | Example | What happens | Why |
|---|---|---|---|
| **Date-range requests in words** | "cancel all my classes from 9 Nov to 13 Nov", "I'm away 9th to 11th November" | Asked back ("which days and weeks?") | The request vocabulary's `period` holds weeks, not calendar dates (dates exist only for club bookings), and no training row has a cancellation or absence between two dates. A range across two weeks can't be one intent, since its days apply to every week |
| **"All my classes"** | "cancel all my classes next week" | A cancellation names one class; matching several asks "which class?" | No `all` in the vocabulary, and no training row |
| **Two-request messages** (v12) | "any day apart from Friday works for my Networks classes" | The course is sometimes lost, or the second course copied into the first | The two most common patterns among v12's held-out misses |

**Ranges made with clicks work today.** The request builder's "A range of dates" (`components/RangeBuilder.tsx`)
cancels or moves every chosen class between two dates, with no model involved. The gap is only in typed
requests. The fix for those: calendar dates in the request vocabulary's `period` (written as said, turned into
weeks and days by code, split into one intent per week when the days differ), an "all my classes" form of
`cancel`, and training rows for both.

## Evaluation

- **H4 is not supported yet.** The concession ledger did not spread burden more evenly than flat weights (Gini
  0.241 against 0.224), because each scenario has a single conflict, which gives the ledger little to act on.
  Scenarios with a sequence of requests among the same people are the planned test.
- **The main comparison mixes models.** Ours runs on the fine-tuned 4B model, the baselines on the much larger
  Gemini. A same-model control on a 20-scenario subset is planned.
- **Faithfulness is not yet checked by people.** Claim faithfulness (0.98) is measured automatically; the judge
  is to be validated against human labels (Cohen's κ), and the faculty pilot waits for ethics clearance.
- **Simulated people.** Negotiation partners are simulators with hidden profiles; real people may answer in ways
  none of the four styles covers.
- **Synthetic data.** Every dataset is generated or team-written, and the handbook is a synthetic stand-in. Real
  requests would be the strongest test.

## Training

- **The linear-attention layers get no adapter.** The adapters' layer pattern (`q_proj`, `k_proj`, `v_proj`,
  `o_proj` and the MLP) was written for ordinary transformer layers. Qwen3.5 is a hybrid: in 24 of its 32 layers
  the attention is linear attention, whose projections have other names, so only the 8 full-attention layers and
  the 32 MLPs are adapted. The tasks were still learned well, but adding the linear-attention projections is an
  untested way to give the adapters more reach (see [models-and-training.md](models-and-training.md#what-is-trained-and-why)).
- **Forgetting when continuing.** A new adapter version that continues from the last one forgets what its new
  rows don't mention unless enough old rows are replayed (v4 and "in week N").

## Running it

- **One GPU server.** All adapters share one `llama-server`; when it is unreachable the app falls back to the
  rule-based stand-ins, which are much weaker (51.6% against 96.4% on reading requests), and requests that would
  change the timetable wait for up to 10 minutes.
- **The local network to the server drops in bursts.** The evaluation scripts wait and try again, and the chat
  test runner resends a message that was answered without the model; results were checked to be the model's.
- **The 12-hour Kaggle limit** splits long training runs into sessions that resume from checkpoints.

Older notes on timetable questions, most of them fixed since, are in [KNOWN_BUGS.md](../../KNOWN_BUGS.md).
