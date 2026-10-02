"""Multi-task training data for the local model (every agent-side LLM call).

The fine-tuned compiler only parses. This module builds data for the other
calls the deployed system makes, with the same system prompts and user
messages as at run time, so a model trained on it drops into ``--local``
unchanged:

* ``reply``: read a stakeholder's free-text answer (``ReplyParser``). Labels
  are free: the decision (accept / counter / reject) is chosen first and the
  simulator model, or a template, writes the text that says it.
* ``explain``: grounded explanations (``Explainer``, mode ``grounded``). The
  teacher (the Gemini agent model) writes claims; a sample is kept only if
  every claim cites known fact IDs and passes the claim checker, every
  option is cited and nothing private leaks.
* ``policy``: the policy agent. The teacher's verdict is kept only if it
  matches the corpus label, cites the gold rules and cites nothing it was
  not shown; the make-up obligation (which the teacher often misses) is set
  from the label.
* ``denials``: more policy examples, no API. Generated rule-breaking
  requests and their legal look-alikes (the same ones ``language.compiler``
  adds), and corpus denials shown with a misread parse (lunch moved an hour,
  a run cut to the limit, or no parse): the verdict comes from the message.
  Targets are the teacher's own answers from ``policy``, which are the same
  text for every denial of a rule. Saved as policy rows.
* ``compile``: the existing compiler data (``language.compiler``).

Conflicts come from benchmark scenarios generated with seeds 1.. (seed 0 is
the evaluation set and is never used); the last seed is the validation
split. Policy examples use the corpus train/val splits.

    uv run python -m training.distill messages --seeds 1-10       # negotiations, solver only (no API)
    uv run python -m training.distill reply                       # simulator model voices replies
    uv run python -m training.distill reply --voice template      # no API
    uv run python -m training.distill explain                     # teacher: agent model
    uv run python -m training.distill policy                      # teacher: agent model
    uv run python -m training.distill denials                     # more policy denials, no API
    uv run python -m training.distill check --files x/reply.jsonl # validate rows made elsewhere (same filters)
    uv run python -m training.distill export                      # data/multitask/{train,val}.jsonl

Every stage writes ``data/distill/<stage>.jsonl``; the Gemini client caches
every call, so a stage stopped by the daily quota resumes where it stopped
when run again.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import threading
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agents.explainer import (
    GROUNDED_PROMPT,
    ClaimChecker,
    Explainer,
    ExplanationOut,
    Fact,
    leaks,
)
from agents.ledger import ConcessionLedger
from agents.negotiation import (
    REPLY_PROMPT,
    Message,
    Negotiator,
    ReplyParser,
    _ParsedReply,
)
from agents.policy import SYSTEM_PROMPT as POLICY_PROMPT
from agents.policy import PolicyAgent, PolicyOutput, load_handbook, query_hints
from agents.priority import PriorityModel
from agents.simulators import Simulator, Window, voice
from core.instance import Instance
from evaluation.benchmark import Scenario, generate, load, save
from language.compiler import gold_output
from language.corpus import (
    CorpusExample,
    ExpectedAction,
    Variant,
    duplicates_held_out,
    extra_denials,
    held_out,
    load_jsonl,
)
from language.llm import DailyQuotaReached, LLMError
from language.parsing import ParseResult, postprocess
from language.rule_parser import RuleParser

DIR = Path("data/distill")
SEMESTER = "2026-1"


def _chat(system: str, user: str, answer: str) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user},
            {"role": "assistant", "content": answer}]


def _write(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _run_all(fn: Callable, items: list, workers: int) -> list:
    """``fn`` over ``items`` in threads; stops cleanly at the daily quota.
    Items whose call failed come back as ``None``."""
    results: list = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fn, x) for x in items]
        for i, fut in enumerate(futures, 1):
            try:
                results.append(fut.result())
            except DailyQuotaReached as e:
                print(f"daily quota reached after {i - 1}/{len(items)}: {e}; rerun later to resume", flush=True)
                pool.shutdown(cancel_futures=True)
                break
            except LLMError as e:
                print(f"[{i}/{len(items)}] failed: {e}", flush=True)
                results.append(None)
            if i % 25 == 0:
                print(f"[{i}/{len(items)}]", flush=True)
    return results


def _teacher(model: str | None):
    from language.llm import GeminiClient, default_model

    return GeminiClient(model or default_model("agent"))


# ---------------------------------------------------------------------------
# Stage 1: negotiation messages (solver only)
# ---------------------------------------------------------------------------


def scenarios_for(seed: int) -> list[Scenario]:
    path = DIR / f"scenarios-s{seed}.jsonl"
    if path.exists():
        return load(path)
    scenarios = generate(seed)
    save(scenarios, path)
    return scenarios


def collect_messages(seeds: list[int]) -> list[dict]:
    """Run the resolution ladder (template explanations, scripted replies)
    on each scenario and keep every message it sends."""
    if 0 in seeds:
        raise ValueError("seed 0 is the evaluation benchmark; do not train on it")
    rows = []
    val_seed = max(seeds)
    for seed in seeds:
        for sc in scenarios_for(seed):
            ledger = ConcessionLedger(list(sc.ledger))
            pm = PriorityModel(sc.instance, ledger=ledger, semester=SEMESTER, baseline=sc.baseline)
            neg = Negotiator(sc.instance, priority=pm, explainer=Explainer(sc.instance), ledger=ledger,
                             semester=SEMESTER, time_limit=20)
            sims = {p.owner: Simulator(sc.instance, p) for p in sc.profiles}
            out = neg.resolve(sc.constraints, sims, baseline=sc.baseline, week=sc.week, private=sc.private,
                              raw_requests=sc.raw_requests)
            for m in out.messages:
                profile = next((p for p in sc.profiles if p.owner == m.to), None)
                rows.append({"id": f"s{seed}-{sc.id}-r{m.round}", "seed": seed, "scenario": sc.id,
                             "split": "val" if seed == val_seed else "train", "private": sc.private,
                             "windows": [w.model_dump() for w in profile.windows] if profile else [],
                             "message": m.model_dump()})
            print(f"seed {seed} {sc.id}: {out.status}, {len(out.messages)} messages", flush=True)
    return rows


def _instances(rows: list[dict]) -> dict[tuple[int, str], Instance]:
    out = {}
    for seed in sorted({r["seed"] for r in rows}):
        for sc in scenarios_for(seed):
            out[(seed, sc.id)] = sc.instance
    return out


# ---------------------------------------------------------------------------
# Stage 2: reading replies
# ---------------------------------------------------------------------------

ACCEPT = ["Option {k} works for me, thanks.", "Let's go with {k}.", "{k} is fine.",
          "I can do option {k}.", "OK, {k} please.", "Happy with {k}, thank you."]
COUNTER = ["Sorry, none of those suit me, but {w} would work.", "Those don't work. Could we do {w} instead?",
           "Not those, I'm afraid. {W} is possible for me.", "I can't make any of them; {w} would be fine though."]
REJECT = ["Sorry, none of those work for me.", "No, I can't move it.", "None of these options work, I'm afraid.",
          "I need to keep my original slot; none of these are possible."]


def _random_window(rng: random.Random, days: list[str], slots_per_day: int, lunch: int | None) -> Window:
    pick_days = sorted(rng.sample(days, rng.choice([1, 1, 2])), key=days.index) if rng.random() < 0.85 else None
    if rng.random() < 0.2 and pick_days:
        return Window(days=pick_days)  # a whole day
    teaching = [s for s in range(slots_per_day) if s != lunch]
    morning = rng.random() < 0.5
    block = [s for s in teaching if lunch is None or (s < lunch) == morning] or teaching
    start = rng.randrange(len(block))
    run = [block[start]]
    for s in block[start + 1:start + rng.choice([1, 2, 3])]:
        if s == run[-1] + 1:
            run.append(s)
    return Window(days=pick_days, slots=run)


def reply_samples(rows: list[dict], *, voice_client=None, per_message: int = 3, seed: int = 0) -> list[dict]:
    """For each message: one accept, one counter and one reject (in random
    order, ``per_message`` of them), each voiced, with the label the reply
    parser must recover."""
    rng = random.Random(seed)
    instances = _instances(rows)
    jobs = []
    for r in rows:
        inst = instances[(r["seed"], r["scenario"])]
        msg = Message.model_validate(r["message"])
        keys = [o.key for o in msg.offers] or ["A"]
        cal = inst.calendar
        kinds = rng.sample(["accept", "counter", "reject"], 3)[:per_message]
        for kind in kinds:
            if kind == "accept":
                k = rng.choice(keys)
                label = _ParsedReply(decision="accept", choice=k)
                say, text = f"You accept option {k}.", rng.choice(ACCEPT).format(k=k)
            elif kind == "counter":
                own = [Window.model_validate(w) for w in r["windows"]]
                w = own[0] if own and rng.random() < 0.4 else _random_window(rng, cal.days, cal.slots_per_day,
                                                                              cal.lunch_slot)
                label = _ParsedReply(decision="counter", counter_days=w.days, counter_slots=w.slots)
                say = f"None of the options work, but {w.text()} would work for you."
                t = w.text()
                text = rng.choice(COUNTER).format(w=t, W=t[0].upper() + t[1:])
            else:
                label = _ParsedReply(decision="reject")
                say, text = "None of the options work for you, and you have nothing else to suggest.", rng.choice(REJECT)
            jobs.append((r, inst, msg, kind, label, say, text))

    def run(job) -> dict:
        r, inst, msg, kind, label, say, text = job
        if voice_client is not None:
            text = voice(voice_client, inst, msg.to, msg.text, say)
        prompt = ReplyParser(None, inst).build_prompt(msg, text)
        return {"id": f"{r['id']}-{kind}", "task": "reply", "split": r["split"],
                "messages": _chat(REPLY_PROMPT, prompt, label.model_dump_json(exclude_none=True))}

    return [x for x in _run_all(run, jobs, workers=4 if voice_client else 1) if x]


# ---------------------------------------------------------------------------
# Stage 3: grounded explanations
# ---------------------------------------------------------------------------


def check_explanation(facts: list[Fact], got: ExplanationOut, checker: ClaimChecker,
                      private: Iterable[str] = ()) -> tuple[ExplanationOut | None, str]:
    """The teacher's claims as a training target, or why they are not one."""
    by_id = {f.id: f for f in facts}
    if not 2 <= len(got.claims) <= 6:
        return None, "claim count"
    clean = []
    for c in got.claims:
        ids = [i.strip().strip("[]") for i in c.facts]
        if not ids or any(i not in by_id for i in ids):
            return None, "unknown fact id"
        if not checker.supported(c.text, [by_id[i] for i in ids]):
            return None, "unsupported claim"
        clean.append({"text": c.text, "facts": ids})
    cited = {i for c in clean for i in c["facts"]}
    if any(f.id.startswith("OPT-") and f.id not in cited for f in facts):
        return None, "option not cited"
    if leaks(" ".join(c["text"] for c in clean), private):
        return None, "leak"
    return ExplanationOut.model_validate({"claims": clean}), "ok"


def explain_samples(rows: list[dict], teacher, *, workers: int = 4) -> tuple[list[dict], Counter]:
    instances = _instances(rows)
    reasons: Counter = Counter()
    lock = threading.Lock()

    def run(r: dict) -> dict | None:
        inst = instances[(r["seed"], r["scenario"])]
        msg = Message.model_validate(r["message"])
        facts = [Fact(f["id"], f["text"]) for f in msg.facts]
        prompt = Explainer(inst).grounded_prompt(facts, msg.to)
        got = teacher.generate(GROUNDED_PROMPT, prompt, ExplanationOut)
        target, why = check_explanation(facts, got, ClaimChecker(inst), r["private"])
        with lock:
            reasons[why] += 1
        if target is None:
            return None
        return {"id": r["id"], "task": "explain", "split": r["split"],
                "messages": _chat(GROUNDED_PROMPT, prompt, target.model_dump_json())}

    return [x for x in _run_all(run, rows, workers) if x], reasons


# ---------------------------------------------------------------------------
# Stage 4: policy agent
# ---------------------------------------------------------------------------

POLICY_ACTIONS = {ExpectedAction.COMPILE, ExpectedAction.DENY, ExpectedAction.ANSWER}


def check_policy(ex: CorpusExample, out: PolicyOutput, shown: set[str]) -> tuple[PolicyOutput | None, str]:
    """The teacher's output as a training target, or why it is not one. The
    make-up obligation is set from the label (the teacher often leaves it
    out); everything else must already be right."""
    cited, obligations = set(out.cited_rules), set(out.obligations)
    if (cited | obligations) - shown:
        return None, "cites a rule it was not shown"
    gold = set(ex.rules)
    if ex.expected_action == ExpectedAction.DENY:
        ok = out.verdict == "forbidden" and gold <= cited
        return (out, "ok") if ok else (None, "deny missed")
    if out.verdict != "allowed":
        return None, "false deny"
    if ex.expected_action == ExpectedAction.ANSWER:
        ok = bool(out.answer) and gold <= cited
        return (out, "ok") if ok else (None, "answer missed")
    want = "P-MAKEUP" in gold
    if want == ("P-MAKEUP" in obligations):
        return out, "ok"
    fixed = [o for o in out.obligations if o != "P-MAKEUP"] + (["P-MAKEUP"] if want else [])
    return out.model_copy(update={"obligations": fixed}), "ok, make-up set from label"


def policy_samples(corpora: list[list[CorpusExample]], instance: Instance, handbook: Path, teacher,
                   *, workers: int = 4, limit: int | None = None) -> tuple[list[dict], Counter]:
    agent = PolicyAgent(load_handbook(handbook), teacher, instance)
    parser = RuleParser(instance)  # the input parse; at run time it comes from the local compiler
    reasons: Counter = Counter()
    lock = threading.Lock()
    seen: set[str] = set()
    jobs = []
    for corpus in corpora:
        for ex in corpus:
            if (ex.split not in ("train", "val") or ex.expected_action not in POLICY_ACTIONS
                    or ex.variant == Variant.UNAUTHORISED or ex.request.raw_text in seen):
                continue
            seen.add(ex.request.raw_text)
            jobs.append(ex)

    def run(ex: CorpusExample) -> dict | None:
        parse = parser.parse(ex.request)
        if parse.action.value not in ("compile", "clarify", "answer"):
            with lock:
                reasons["parser skipped"] += 1
            return None
        text = ex.request.raw_text
        retrieved = agent.retrieve(f"{text} {query_hints(instance, parse)}")
        if not set(ex.rules) <= {r.id for r in retrieved}:
            with lock:
                reasons["gold rule not retrieved"] += 1
            return None
        prompt = agent.build_prompt(text, parse, retrieved)
        out = teacher.generate(POLICY_PROMPT, prompt, PolicyOutput)
        target, why = check_policy(ex, out, {r.id for r in retrieved})
        with lock:
            reasons[why] += 1
        if target is None:
            return None
        return {"id": ex.id, "task": "policy", "split": ex.split,
                "messages": _chat(POLICY_PROMPT, prompt, target.model_dump_json(exclude_none=True))}

    return [x for x in _run_all(run, jobs[:limit], workers) if x], reasons


# ---------------------------------------------------------------------------
# Stage 4b: more denials (no API)
# ---------------------------------------------------------------------------


def canonical_answers(rows: list[dict]) -> dict[str, str]:
    """The teacher's most common accepted answer for each denied rule, and
    for a plain allowed preference (``"allowed"``)."""
    by: dict[str, Counter] = {}
    for r in rows:
        text = r["messages"][-1]["content"]
        out = PolicyOutput.model_validate_json(text)
        if out.verdict == "forbidden" and len(out.cited_rules) == 1:
            key = out.cited_rules[0]
        elif out.verdict == "allowed" and not (out.cited_rules or out.obligations or out.answer):
            key = "allowed"
        else:
            continue
        by.setdefault(key, Counter())[text] += 1
    return {k: c.most_common(1)[0][0] for k, c in by.items()}


def misread(instance: Instance, parse: ParseResult, rule: str) -> ParseResult:
    """What a weaker parser makes of a rule-breaking request: the lunch hour
    read as the hour before, or a run cut to the limit."""
    cal, limit = instance.calendar, instance.policy.max_consecutive
    wrong = [cal.lunch_slot - 1] if rule == "P-LUNCH" else list(range(limit))
    constraints = [c.model_copy(update={"when": c.when.model_copy(update={"slots": wrong})})
                   for c in parse.constraints]
    return ParseResult(request=parse.request, output=parse.output, constraints=constraints)


def denial_samples(extra: list[CorpusExample], corpora: list[list[CorpusExample]], instance: Instance,
                   handbook: Path, answers: dict[str, str], *, seed: int = 0,
                   misread_share: float = 0.4) -> tuple[list[dict], Counter]:
    agent = PolicyAgent(load_handbook(handbook), None, instance)
    rng = random.Random(seed)
    reasons: Counter = Counter()
    jobs: list[tuple[CorpusExample, str]] = []  # (example, how the parse is shown)
    for ex in extra:
        jobs.append((ex, "gold"))
        if ex.expected_action == ExpectedAction.DENY and rng.random() < misread_share:
            jobs.append((ex, rng.choice(["misread", "none"])))
    seen: set[str] = set()
    for corpus in corpora:  # corpus denials already have a gold-parse row from the teacher
        for ex in corpus:
            if ex.split == "train" and ex.expected_action == ExpectedAction.DENY and ex.request.raw_text not in seen:
                seen.add(ex.request.raw_text)
                jobs.append((ex, rng.choice(["misread", "none"])))
    rows = []
    for ex, shown in jobs:
        gold = gold_output(ex, instance)
        if gold is None:
            reasons["no gold parse"] += 1
            continue
        parse = postprocess(instance, ex.request, gold)
        if shown == "misread":
            parse = misread(instance, parse, ex.violates_rule)
        elif shown == "none":
            parse = None
        text = ex.request.raw_text
        retrieved = agent.retrieve(f"{text} {query_hints(instance, parse)}")
        if not set(ex.rules) <= {r.id for r in retrieved}:
            reasons["gold rule not retrieved"] += 1
            continue
        key = ex.violates_rule if ex.expected_action == ExpectedAction.DENY else "allowed"
        if key not in answers:
            reasons[f"no teacher answer for {key}"] += 1
            continue
        reasons[f"{key} ({shown} parse)"] += 1
        rows.append({"id": f"{ex.id}-{shown}", "task": "policy", "split": "train",
                     "messages": _chat(POLICY_PROMPT, agent.build_prompt(text, parse, retrieved), answers[key])})
    return rows, reasons


# ---------------------------------------------------------------------------
# Checking data made elsewhere (e.g. a batch teacher run by hand)
# ---------------------------------------------------------------------------

SYSTEM = {"explain": (GROUNDED_PROMPT, ExplanationOut), "reply": (REPLY_PROMPT, _ParsedReply),
          "policy": (POLICY_PROMPT, PolicyOutput)}
_FACT = re.compile(r"^\[([^\]]+)\] (.*)$")
_REPLY = re.compile(r"Options offered:\n(.*?)\n\nReply:\n<reply>\n(.*)\n</reply>$", re.S)
_MESSAGE = re.compile(r"<message>\n(.*)\n</message>", re.S)
_SHOWN = re.compile(r"^\[([A-Z0-9-]+)\] §", re.M)
_ROOM = re.compile(r"\b(?:Lab|Room|Hall|LH) ?[A-Z]?-?\d+\b")


def _name_list(texts: Iterable[str]):
    """A stand-in instance for the claim checker when the facts were not made
    from a saved scenario: every faculty surname, course title and room the
    generators use."""
    from types import SimpleNamespace

    from core.generator import SURNAMES
    from evaluation.benchmark import COURSES

    rooms = sorted({m for t in texts for m in _ROOM.findall(t)})
    return SimpleNamespace(faculty=[SimpleNamespace(id=f"F{i}", name=f"Dr. {s}") for i, s in enumerate(SURNAMES)],
                           rooms=[SimpleNamespace(id=r, name=r) for r in rooms], groups=[],
                           course_titles=dict(enumerate(COURSES)))


def check_rows(task: str, rows: list[dict], corpus: dict[str, CorpusExample] | None = None) -> tuple[list[dict], Counter]:
    """Keep the rows a teacher run produced that the stage itself would have
    kept. Policy rows take their split from the corpus; test-split requests
    are dropped, since the evaluations score on them."""
    system, schema = SYSTEM[task]
    why: Counter = Counter()
    kept, seen = [], set()
    checker = ClaimChecker(_name_list(r["messages"][1]["content"] for r in rows)) if task == "explain" else None
    for r in rows:
        m = r["messages"]
        if [x["role"] for x in m] != ["system", "user", "assistant"] or m[0]["content"] != system:
            why["format"] += 1
            continue
        if m[1]["content"] in seen:
            why["duplicate"] += 1
            continue
        try:
            answer = schema.model_validate_json(m[2]["content"])
        except ValueError:
            why["answer schema"] += 1
            continue
        reason, split = "ok", r.get("split", "train")
        if task == "explain":
            facts = [Fact(*g.groups()) for line in m[1]["content"].split("\n") if (g := _FACT.match(line))]
            target, reason = check_explanation(facts, answer, checker)
            if target is not None:
                m = [*m[:2], {"role": "assistant", "content": target.model_dump_json()}]
        elif task == "reply":
            g = _REPLY.search(m[1]["content"])
            letters = {line[:1] for line in g.group(1).split("\n")} if g else set()
            if g is None:
                reason = "format"
            elif answer.decision == "accept" and answer.choice not in letters:
                reason = "accepts a letter not offered"
            elif answer.decision == "counter" and not (answer.counter_days or answer.counter_slots):
                reason = "empty counter"
            elif answer.decision == "counter" and 4 in (answer.counter_slots or []):
                reason = "counter includes lunch"
        else:
            g = _MESSAGE.search(m[1]["content"])
            ex = corpus.get(g.group(1).strip()) if g else None
            if ex is None:
                reason = "message not in corpus"
            elif ex.split not in ("train", "val"):
                reason = f"corpus {ex.split} split"
            else:
                split = ex.split
                target, reason = check_policy(ex, answer, set(_SHOWN.findall(m[1]["content"].split("# Calendar")[0])))
                if target is not None:
                    m = [*m[:2], {"role": "assistant", "content": target.model_dump_json(exclude_none=True)}]
        why[reason] += 1
        if reason.startswith("ok"):
            seen.add(m[1]["content"])
            kept.append({**r, "task": task, "split": split, "messages": m})
    return kept, why


def _corpus_index(paths: list[Path], instance: Instance) -> dict[str, CorpusExample]:
    index: dict[str, CorpusExample] = {}
    for p in paths:
        for ex in load_jsonl(p, instance):
            index.setdefault(ex.request.raw_text.strip(), ex)
    return index


# ---------------------------------------------------------------------------
# Stage 5: export
# ---------------------------------------------------------------------------


def export(out_dir: Path, *, compiler_dir: Path, max_per_task: int, seed: int = 0,
           held: dict[str, set[str]] | None = None) -> dict:
    """Merge the tasks into one train/val set; each task is capped at
    ``max_per_task`` training examples so none dominates. With ``held`` (the
    corpus's val and test texts), a row whose message repeats a request of a
    later split is dropped."""
    rng = random.Random(seed)
    by_task: dict[str, list[dict]] = {}
    for split in ("train", "val"):
        path = compiler_dir / f"{split}.jsonl"
        if path.exists():
            by_task.setdefault("compile", []).extend(
                {**r, "task": "compile", "split": split} for r in _read(path))
    for task, files in (("reply", ["reply"]), ("explain", ["explain"]), ("policy", ["policy", "denials"])):
        for name in files:
            if (DIR / f"{name}.jsonl").exists():
                by_task.setdefault(task, []).extend(_read(DIR / f"{name}.jsonl"))
    splits: dict[str, list[dict]] = {"train": [], "val": []}
    counts: dict[str, dict[str, int]] = {}
    for task, rows in by_task.items():
        for split in splits:
            part = [r for r in rows if r["split"] == split]
            if held is not None:
                keep = [r for r in part if not ((g := _MESSAGE.search(r["messages"][1]["content"]))
                                                and duplicates_held_out(g.group(1), split, held))]
                if len(keep) < len(part):
                    counts.setdefault(task, {})[f"{split}_dropped_duplicates"] = len(part) - len(keep)
                part = keep
            rng.shuffle(part)
            if split == "train":
                part = part[:max_per_task]
            splits[split].extend(part)
            counts.setdefault(task, {})[split] = len(part)
    for split, rows in splits.items():
        rng.shuffle(rows)
        _write(out_dir / f"{split}.jsonl",
               ({"id": r["id"], "task": r["task"], "messages": r["messages"]} for r in rows))
    longest = max((sum(len(m["content"]) for m in r["messages"]), r["task"]) for r in splits["train"])
    return {"counts": counts, "longest_train_chars": longest}


def _seeds(text: str) -> list[int]:
    if "-" in text:
        a, b = text.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(s) for s in text.split(",")]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["messages", "reply", "explain", "policy", "denials", "check", "export"])
    ap.add_argument("--seeds", default="1-10", help="scenario seeds for messages (never 0); the last is val")
    ap.add_argument("--voice", choices=["gemini", "template"], default="gemini",
                    help="reply: who writes the reply text")
    ap.add_argument("--per-message", type=int, default=3, help="reply: samples per message (max 3)")
    ap.add_argument("--teacher-model", default=None, help="explain/policy: default the agent model")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None, help="reply/explain/policy: first N items (smoke test)")
    ap.add_argument("--corpus", type=Path, nargs="+",
                    default=[Path("data/requests.jsonl"), Path("data/requests-para.jsonl")])
    ap.add_argument("--instance", type=Path, default=Path("data/synthetic-cse-s0.json"))
    ap.add_argument("--handbook", type=Path, default=Path("data/handbook.md"))
    ap.add_argument("--compiler-dir", type=Path, default=Path("data/compiler"))
    ap.add_argument("--out", type=Path, default=Path("data/multitask"))
    ap.add_argument("--max-per-task", type=int, default=900)
    ap.add_argument("--extra-denials", type=int, default=150,
                    help="denials: generated requests (as language.compiler --extra-denials; same seed, same requests)")
    ap.add_argument("--files", type=Path, nargs="+", default=None,
                    help="check: files named <task>.jsonl (default: data/distill/{reply,explain,policy}.jsonl); "
                         "the checked rows replace data/distill/<task>.jsonl")
    args = ap.parse_args()

    if args.stage == "messages":
        n = _write(DIR / "messages.jsonl", collect_messages(_seeds(args.seeds)))
        print(f"wrote {n} messages to {DIR / 'messages.jsonl'}")
    elif args.stage == "reply":
        from language.llm import GeminiClient, default_model

        client = GeminiClient(default_model("simulator")) if args.voice == "gemini" else None
        rows = reply_samples(_read(DIR / "messages.jsonl")[: args.limit], voice_client=client, per_message=args.per_message)
        print(f"wrote {_write(DIR / 'reply.jsonl', rows)} reply examples; "
              f"labels {dict(Counter(json.loads(r['messages'][2]['content'])['decision'] for r in rows))}")
    elif args.stage == "explain":
        rows, reasons = explain_samples(_read(DIR / "messages.jsonl")[: args.limit], _teacher(args.teacher_model),
                                        workers=args.workers)
        print(f"wrote {_write(DIR / 'explain.jsonl', rows)} explanations; teacher outputs: {dict(reasons)}")
    elif args.stage == "policy":
        instance = Instance.model_validate_json(args.instance.read_text(encoding="utf-8"))
        rows, reasons = policy_samples([load_jsonl(p, instance) for p in args.corpus], instance, args.handbook,
                                       _teacher(args.teacher_model), workers=args.workers, limit=args.limit)
        print(f"wrote {_write(DIR / 'policy.jsonl', rows)} policy examples; outcomes: {dict(reasons)}")
    elif args.stage == "denials":
        instance = Instance.model_validate_json(args.instance.read_text(encoding="utf-8"))
        corpora = [load_jsonl(p, instance) for p in args.corpus]
        held = [e for c in corpora for e in c if e.split in ("val", "test")]
        extra = extra_denials(instance, args.extra_denials, seed=1, exclude=held, near_miss=0.35)
        rows, reasons = denial_samples(extra, corpora, instance, args.handbook, canonical_answers(_read(DIR / "policy.jsonl")))
        print(f"wrote {_write(DIR / 'denials.jsonl', rows)} policy examples; {dict(reasons)}")
    elif args.stage == "check":
        instance = Instance.model_validate_json(args.instance.read_text(encoding="utf-8"))
        corpus = _corpus_index(args.corpus, instance)
        for path in args.files or [DIR / f"{t}.jsonl" for t in ("reply", "explain", "policy")]:
            task = path.stem.split("-")[0]
            given = _read(path)
            rows, why = check_rows(task, given, corpus)
            print(f"{path}: kept {len(rows)}/{len(given)} "
                  f"({dict(Counter(r['split'] for r in rows))}); {dict(why)}")
            _write(DIR / f"{task}.jsonl", rows)
    else:
        instance = Instance.model_validate_json(args.instance.read_text(encoding="utf-8"))
        report = export(args.out, compiler_dir=args.compiler_dir, max_per_task=args.max_per_task,
                        held=held_out(load_jsonl(p, instance) for p in args.corpus))
        print(json.dumps(report, indent=1))
        print(f"upload {args.out}/ as a Kaggle dataset and train with notebooks/train_compiler_kaggle.ipynb")


if __name__ == "__main__":
    main()
