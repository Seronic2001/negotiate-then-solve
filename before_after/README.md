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

### Left for Phase 2

The lookup schema version and migrations: their first use is the v3 -> v4 conversion of the training rows.
