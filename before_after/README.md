# Before and after

One folder per phase of the plan to the final submission (15 Nov 2026). In each: the cases (`requests.jsonl`),
the results before the phase's changes (`before.jsonl`) and after them (`after.jsonl`). A measurement a phase only
starts (a new test set) has its own subfolder, with `before.jsonl` now and `after.jsonl` once a later phase changes
what it measures.

## Phase 1: mixed messages, labels, new test sets (3 Nov)

### Chat: a question and a request (or a rule question) in one message: `phase_1/`

26 messages to the side chat (`POST /api/chat`) as Dr. Menon, with `nts-lookup-v3` on the GPU server, the chat
emptied before each. Run with `uv run python before_after/run.py before_after/phase_1 --out before|after`.

| | before | after |
|---|---|---|
| question + request (8) | 0 | 8 |
| several questions + request(s) (6) | 0 | 6 |
| question + rule question (4) | 0 | 3 |
| controls: request, question, rule only (8) | 8 | 8 |
| **all** | **8/26** | **25/26** |

Before, request words sent the whole message on as a request (the questions went unanswered); a rule question
next to a timetable question was dropped. The change (`World.read_message`, `chat_send`'s `_other_parts`,
`ToolAgent.others`): with v3 up, v3 reads every message (it was trained on 150 mixed ones; the request is its
`none` part), the questions are answered, and the rest follows: a rule answer, and one "send as a request?" card
for every request part, which shows what would be sent. With the model down, request words work as before.

Still wrong, for v3.1 / v4 training data:
- P1-17: "How many hours can a teacher teach in a row?" read as `describe`: the rule question is not seen.
- P1-15 passes, but its rule answer is about working hours, not online classes: the rule reader gets the whole
  message ("Friday" pulls in §2.1); asked alone it finds §3.4. The card likewise holds the whole message. Fix:
  each part's own words (`request` on v3.1's `none` parts, `text` in v4).

### Test labels older than v3: `phase_1/labels/`

v3 reads "was my class cancelled?" with `change: cancelled`, "any gaps on Monday?" as `gaps`, "what week is it?"
as `calendar`; the labels were written before those fields and tools. Seven templates in
`data/lookup-test-templates.jsonl` now accept that reading too (`also`). Test set A, v3: **330 -> 346 / 362**
(16 questions; their readings are the same in both files, only the labels changed).

### Long messages: `phase_1/multi/` (new: `evaluation.multi_set`)

200 messages of 2 to 5 parts from the TEST templates only: 1 to 5 questions, 0 to 2 requests, a rule question in
34; 72 joined in ways the training data never joins them (new lines, "Then", "Also,"). Baseline, v3:

| | right |
|---|---|
| whole message (every lookup, and the other parts counted right) | 111/200 |
| every lookup right | 113/200 |
| question parts | 440/561 (78%) |
| requests found (messages with one) | 112/123 |
| by questions: 1 / 2 / 3 / 4 / 5 | 8/12, 45/67, 41/77, 14/36, 3/8 |
| joined as in training / new ways | 75/128, 36/72 |

Misses: a lookup wrong in 62 messages (a few templates again and again: T2-008, T-139's dates, T3-016), the
number of lookups wrong in 25 (15 too many, 10 too few), requests or rule questions counted wrong in 29 (16 a
request missed).

### Memory, then lookup: `phase_1/end_to_end/` (new: `evaluation.end_to_end`)

memory's 400 test conversations through `nts-memory-v1`, then `nts-lookup-v3`. Right when the rewrite is looked
up as the expected rewrite is (the lookups to expect are v3's reading of the expected message: this measures what
memory loses, not v3's own mistakes).

| | right |
|---|---|
| end to end | **387/400** |
| memory alone (memory_set's check) | 385/400 |
| read as typed, without memory | 146/400 |
| misses by stage | memory 12, lookup 1 |

Memory is what makes follow-ups work: without it, 146 of 400 are looked up right. Three of memory's 15 "wrong"
rewrites (kind `list`) are still looked up right.

## Phase 2: the lookup vocabulary, v4 (3 Nov)

Code only: no model yet, so no before and after of a model here (that is Phase 5, v3 against v3.1 and v4 on
every set above). What Phase 2 checks is that v4 can say everything v3 says, with the same lookups.

`agents/lookups_v4.py`: `LookupsV4`, a part per thing a message asks, each tool with only its own fields
(20 kinds of part, at most 8 a message). Shared pieces: `who` (names as written, roles, unknown), `when`
(days, today/tomorrow, dates, part of the day, clock times `at` / `after` / `before`, and the request
vocabulary's `Period`: `next_week`, weeks, from/to), `room`, and `which` for the class `move_options` moves.
`request` and `rule` parts carry their own words; `other` is left out. The code works out slots and week numbers
(`language.intents.slots` / `weeks`), then v3's checks run unchanged (`to_choice` gives a `ChoiceV3`), so
`Answerer` and every test set treat v3 and v4 alike. `LOOKUP_SCHEMA = 4`.

v3's training rows in v4 (`training/lookup_data_v4.py`, `data/lookup-train-v4/`): each row's v4 answer is read
by `ToolAgent` next to its v3 answer, and kept only if the lookups are the same.

| | v3 rows | in v4, same lookups | left out |
|---|---|---|---|
| train | 2,503 | 2,399 | 104 |
| val | 495 | 459 | 36 |
| distilled (Gemini's rewordings) | 583 | 571 | 12 |

Every row left out is a mixed message: v3's "none" didn't keep the request's words, so its v4 `request` part
can't be written. Phase 3 writes those messages again, with the words, for v3.1 and v4 alike. No row gives other
lookups. v4 rows are about a third shorter (prompt 3,805 characters against 5,786; answers about the same), so
training takes less time.

Found on the way, and fixed in the schema: `free_rooms` and `who_is_free` had no `unknown` ("is the auditorium
free?" would have listed lecture rooms).

In the chat with v4 (`tests/test_lookups_v4.py`): a rule question inside a mixed message is answered from its own
words (P1-15's "online classes" now finds §3.4, not §2.1), and the request card holds only the request.
