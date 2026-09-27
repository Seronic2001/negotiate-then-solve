"""LLM paraphrasing of the request corpus (proposal Section 12.1).

The templated corpus is too regular: System One scores 100% on it and the
System Two numbers are optimistic. This rewrites every request in one of
several registers with the simulator model, keeping the labels unchanged.

    uv run python -m language.paraphrase            # data/requests.jsonl -> data/requests-para.jsonl

A paraphrase must not change what the labels say, so each one is checked
deterministically before it is accepted:

* the same day names and the same numbers (weeks, hours, counts);
* the same people, rooms, groups and course titles (the sender's own name,
  e.g. in a sign-off, may be dropped);
* an injected instruction is removed before paraphrasing and appended again
  verbatim afterwards, so injection labels stay exact.

Rejected items are retried with another style; items that never pass keep
their template text and are marked ``paraphrased: false`` in the report.
Hedging ("would prefer" vs "cannot") cannot be checked by rule, so the
prompt insists on it and a sample should be read by a person.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel

from core.instance import Instance

from .corpus import INJECTIONS, CorpusExample, load_jsonl, save_jsonl
from .llm import DailyQuotaReached, GeminiClient, default_model

STYLES = [
    "a short, informal chat message: lowercase is fine, no greeting, clipped sentences",
    "a polite, formal email to the timetable office",
    "a hurried phone message with one or two small typos (never inside names, days or numbers)",
    "a wordy message that adds some harmless background (never new days, dates, times or people)",
    "plain and direct, one or two sentences",
    "the phrasing common in Indian university offices ('kindly', 'out of station', 'do the needful')",
]

SYSTEM_PROMPT = """You rewrite messages sent to a university timetable office, to give a
test set realistic variety. Rewrite each item in the style given for it.

Keep the meaning exactly:
- Same days, weeks, times, counts, people, courses, groups and rooms. Write
  numbers as digits ("week 7", not "the seventh week"; "10 am" may become
  "10am" or "10:00"). Day names may be shortened (Tue, Thurs).
- Keep names of people, rooms, courses and groups exactly as written.
- Add no facts: no new days, dates, times, reasons or people.
- Keep vague messages vague and precise messages precise.
- Keep the strength of the request: a wish ("would prefer", "if possible")
  stays a wish, and a "cannot" or "must" stays a firm requirement.
- Keep who is asking about whom (my classes vs. a colleague's classes).
Return every id with its rewritten text only."""


class _Item(BaseModel):
    id: str
    text: str


class _Batch(BaseModel):
    items: list[_Item]


# ---------------------------------------------------------------------------
# Fidelity check
# ---------------------------------------------------------------------------

_DAY = re.compile(r"\b(mon|tue|tues|wed|wednes|thu|thur|thurs|fri|sat|satur|sun)(?:day)?s?\b", re.I)
_NUM = re.compile(r"\d+")
_IGNORED_NUMBERS = {"0", "00"}  # "9 am" -> "9:00 am"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace(".", "")).lower()


class FidelityCheck:
    def __init__(self, instance: Instance) -> None:
        names = ([f.name for f in instance.faculty] + [r.name for r in instance.rooms]
                 + [r.id for r in instance.rooms] + [g.name for g in instance.groups]
                 + list(instance.course_titles.values()))
        # Longest first so "Dr Rao 2" is not read as "Dr Rao".
        alternatives = sorted({_norm(n) for n in names}, key=len, reverse=True)
        self._entity = re.compile(r"\b(" + "|".join(map(re.escape, alternatives)) + r")\b(?!\s\d)")
        self._faculty = {f.id: _norm(f.name) for f in instance.faculty}

    def entities(self, text: str) -> set[str]:
        return set(self._entity.findall(_norm(text)))

    @staticmethod
    def days(text: str) -> set[str]:
        return {m[:3].lower() for m in _DAY.findall(text)}

    @staticmethod
    def numbers(text: str) -> set[str]:
        return {n.lstrip("0") or "0" for n in _NUM.findall(text)} - _IGNORED_NUMBERS

    def problems(self, original: str, paraphrase: str, sender_id: str) -> list[str]:
        out = []
        if self.days(original) != self.days(paraphrase):
            out.append(f"days {sorted(self.days(original))} -> {sorted(self.days(paraphrase))}")
        if self.numbers(original) != self.numbers(paraphrase):
            out.append(f"numbers {sorted(self.numbers(original))} -> {sorted(self.numbers(paraphrase))}")
        own = {self._faculty.get(sender_id)}
        before, after = self.entities(original) - own, self.entities(paraphrase) - own
        if before != after:
            out.append(f"entities {sorted(before)} -> {sorted(after)}")
        return out


# ---------------------------------------------------------------------------
# Paraphrasing
# ---------------------------------------------------------------------------


def split_injection(text: str) -> tuple[str, str]:
    """(body, suffix) where suffix is the injected instruction with the
    separator that preceded it, or "" if the text has none."""
    for inj in INJECTIONS:
        i = text.rfind(inj)
        if i > 0:
            return text[: i - 1], text[i - 1 :]
    return text, ""


class GeminiParaphraser:
    """Implements ``corpus.Paraphraser``; used here in batches to save quota."""

    def __init__(self, client: GeminiClient, temperature: float = 0.9) -> None:
        self.client = client
        self.temperature = temperature

    def batch(self, items: list[tuple[str, str, str]]) -> dict[str, str]:
        """``items`` are (id, style, text); returns id -> paraphrase."""
        prompt = "\n\n".join(f'<item id="{i}" style="{s}">\n{t}\n</item>' for i, s, t in items)
        out = self.client.generate(SYSTEM_PROMPT, prompt, _Batch, temperature=self.temperature)
        return {it.id: it.text.strip() for it in out.items}

    def paraphrase(self, text: str, n: int) -> list[str]:
        items = [(str(k), STYLES[k % len(STYLES)], text) for k in range(n)]
        got = self.batch(items)
        return [got[i] for i, _, _ in items if i in got]


def paraphrase_corpus(
    corpus: list[CorpusExample],
    instance: Instance,
    paraphraser: GeminiParaphraser,
    *,
    batch_size: int = 10,
    rounds: int = 3,
    workers: int = 4,
    seed: int = 0,
) -> tuple[list[CorpusExample], dict]:
    check = FidelityCheck(instance)
    rng = random.Random(seed)
    style = {ex.id: rng.randrange(len(STYLES)) for ex in corpus}
    parts = {ex.id: split_injection(ex.request.raw_text) for ex in corpus}
    accepted: dict[str, str] = {}
    rejected: dict[str, list[str]] = {}
    log: list[dict] = []  # every rejection, including ones a later round fixed
    pending = [ex for ex in corpus]
    stopped = None

    for rnd in range(rounds):
        if not pending:
            break
        batches = [pending[i : i + batch_size] for i in range(0, len(pending), batch_size)]

        def run(batch: list[CorpusExample], rnd: int = rnd) -> dict[str, str]:
            return paraphraser.batch([(ex.id, STYLES[(style[ex.id] + rnd) % len(STYLES)], parts[ex.id][0])
                                      for ex in batch])

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run, b) for b in batches]
            for k, (batch, fut) in enumerate(zip(batches, futures, strict=True), 1):
                try:
                    got = fut.result()
                except DailyQuotaReached as e:
                    stopped = str(e)
                    pool.shutdown(cancel_futures=True)
                    break
                for ex in batch:
                    text = got.get(ex.id)
                    if not text:
                        rejected[ex.id] = ["missing from response"]
                        continue
                    problems = check.problems(parts[ex.id][0], text, ex.request.sender_id)
                    if problems:
                        rejected[ex.id] = problems
                        log.append({"id": ex.id, "round": rnd + 1, "text": text, "problems": problems})
                    else:
                        accepted[ex.id] = text
                        rejected.pop(ex.id, None)
                print(f"round {rnd + 1} batch {k}/{len(batches)}: accepted {len(accepted)}/{len(corpus)}",
                      flush=True)
        if stopped:
            break
        pending = [ex for ex in corpus if ex.id not in accepted]

    out = []
    for ex in corpus:
        new = ex.model_copy(deep=True)
        if ex.id in accepted:
            new.template_text = ex.request.raw_text
            new.request.raw_text = accepted[ex.id] + parts[ex.id][1]
        out.append(new)
    report = {
        "model": paraphraser.client.model,
        "n": len(corpus),
        "paraphrased": len(accepted),
        "kept_template": sorted(set(ex.id for ex in corpus) - set(accepted)),
        "rejections": rejected,
        "rejection_log": log,
        "stopped": stopped,
        "usage": vars(paraphraser.client.usage),
    }
    return out, report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", type=Path, default=Path("data/requests.jsonl"))
    ap.add_argument("--instance", type=Path, default=Path("data/synthetic-cse-s0.json"))
    ap.add_argument("--out", type=Path, default=Path("data/requests-para.jsonl"))
    ap.add_argument("--model", default=None, help="default: the simulator model (GEMINI_SIM_MODEL)")
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None, help="only the first N requests (for a trial run)")
    args = ap.parse_args()

    instance = Instance.model_validate_json(args.instance.read_text(encoding="utf-8"))
    corpus = load_jsonl(args.corpus, instance)[: args.limit]
    client = GeminiClient(args.model or default_model("simulator"))
    out, report = paraphrase_corpus(corpus, instance, GeminiParaphraser(client),
                                    batch_size=args.batch_size, workers=args.workers)
    save_jsonl(out, args.out)
    report_path = args.out.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"paraphrased {report['paraphrased']}/{report['n']} -> {args.out}; report {report_path}")
    if report["stopped"]:
        print(f"stopped early: {report['stopped']} (rerun tomorrow; the cache resumes)")


if __name__ == "__main__":
    main()
