"""Distillation data for the local model: filters and labels. No API calls
(stub teacher, template voices)."""

import json
import random
from pathlib import Path

from agents.explainer import ClaimChecker, ExplanationOut, Fact
from agents.negotiation import _ParsedReply
from agents.policy import PolicyOutput
from core.instance import Instance
from core.scenarios import uc3_lab_contention
from language.corpus import load_jsonl
from training import distill

FACTS = [Fact("C-A", "Dr. Khan needs the Algorithms practical (C3-P) on Monday in the afternoon (Tier 4, operational requirement)."),
         Fact("OPT-A", "Option A: the Algorithms practical (C3-P) on Tuesday at 2 pm in Lab 2. The solver confirms this works.")]


def _claims(*claims):
    return ExplanationOut.model_validate({"claims": [{"text": t, "facts": f} for t, f in claims]})


def test_explanation_filter():
    checker = ClaimChecker(uc3_lab_contention()[0])
    good = _claims(("You asked for Monday afternoon, but that cannot work.", ["C-A"]),
                   ("Option A moves it to Tuesday at 2 pm in Lab 2.", ["[OPT-A]"]))
    out, why = distill.check_explanation(FACTS, good, checker)
    assert why == "ok" and out.claims[1].facts == ["OPT-A"]  # brackets stripped in the target
    wrong_day = _claims(("You asked for Monday afternoon.", ["C-A"]), ("Option A is on Friday at 2 pm.", ["OPT-A"]))
    assert distill.check_explanation(FACTS, wrong_day, checker) == (None, "unsupported claim")
    no_option = _claims(("You asked for Monday afternoon.", ["C-A"]), ("That cannot work.", ["C-A"]))
    assert distill.check_explanation(FACTS, no_option, checker)[1] == "option not cited"
    leaky = _claims(("You asked for Monday afternoon for a hospital visit.", ["C-A"]),
                    ("Option A is on Tuesday at 2 pm in Lab 2.", ["OPT-A"]))
    assert distill.check_explanation(FACTS, leaky, checker)[1] == "leak"


def test_random_windows_are_contiguous_and_skip_lunch():
    rng = random.Random(1)
    for _ in range(200):
        w = distill._random_window(rng, ["Mon", "Tue", "Wed", "Thu", "Fri"], 8, 4)
        if w.slots:
            assert 4 not in w.slots and w.slots == list(range(w.slots[0], w.slots[-1] + 1))


def test_policy_filter():
    inst = Instance.model_validate_json(open("data/synthetic-cse-s0.json", encoding="utf-8").read())
    corpus = load_jsonl(Path("data/requests.jsonl"), inst)
    deny = next(ex for ex in corpus if ex.expected_action.value == "deny" and ex.rules)
    shown = set(deny.rules) | {"P-OTHER"}
    ok = PolicyOutput(verdict="forbidden", cited_rules=list(deny.rules), explanation="x")
    assert distill.check_policy(deny, ok, shown) == (ok, "ok")
    assert distill.check_policy(deny, ok.model_copy(update={"verdict": "allowed"}), shown)[0] is None
    assert distill.check_policy(deny, ok.model_copy(update={"cited_rules": ["P-NOPE"]}), shown)[1] == \
        "cites a rule it was not shown"
    makeup = next(ex for ex in corpus if ex.expected_action.value == "compile" and "P-MAKEUP" in ex.rules)
    allowed = PolicyOutput(verdict="allowed", explanation="x")
    fixed, why = distill.check_policy(makeup, allowed, {"P-MAKEUP"})
    assert fixed.obligations == ["P-MAKEUP"] and why == "ok, make-up set from label"


def test_export_balances_and_keeps_splits(tmp_path, monkeypatch):
    monkeypatch.setattr(distill, "DIR", tmp_path / "distill")
    label = _ParsedReply(decision="reject").model_dump_json(exclude_none=True)
    rows = [{"id": f"r{i}", "task": "reply", "split": "train" if i < 8 else "val",
             "messages": distill._chat("s", "u", label)} for i in range(10)]
    distill._write(tmp_path / "distill" / "reply.jsonl", rows)
    comp = tmp_path / "compiler"
    distill._write(comp / "train.jsonl", [{"id": "c1", "messages": distill._chat("s", "u", "{}")}])
    report = distill.export(tmp_path / "out", compiler_dir=comp, max_per_task=5)
    assert report["counts"] == {"compile": {"train": 1, "val": 0}, "reply": {"train": 5, "val": 2}}
    train = [json.loads(line) for line in (tmp_path / "out" / "train.jsonl").read_text().splitlines()]
    assert {r["task"] for r in train} == {"compile", "reply"} and set(train[0]) == {"id", "task", "messages"}


def test_check_rows_resplits_policy_and_filters_replies():
    inst = Instance.model_validate_json(open("data/synthetic-cse-s0.json", encoding="utf-8").read())
    corpus = distill._corpus_index([Path("data/requests.jsonl")], inst)
    by_split = {}
    for ex in corpus.values():
        if ex.expected_action.value == "compile" and not ex.rules:
            by_split.setdefault(ex.split, ex)
    answer = PolicyOutput(verdict="allowed", explanation="x").model_dump_json(exclude_none=True)
    rows = [{"id": s, "split": "train", "messages": distill._chat(
        distill.POLICY_PROMPT, f"# Rules retrieved\n\n# Calendar\n\n<message>\n{ex.request.raw_text}\n</message>", answer)}
        for s, ex in by_split.items()]
    kept, why = distill.check_rows("policy", rows, corpus)
    assert {r["split"] for r in kept} == {"train", "val"} and why["corpus test split"] == 1

    def reply(label):
        user = ("Slots: 0=9 am. Days: Mon.\n\nOptions offered:\nA) x on Monday at 9 am in Lab 1\n\n"
                "Reply:\n<reply>\nfine\n</reply>")
        return {"id": "r", "messages": distill._chat(distill.REPLY_PROMPT, user, label)}
    kept, why = distill.check_rows("reply", [reply('{"decision":"accept","choice":"B"}')])
    assert not kept and why["accepts a letter not offered"] == 1


def test_denials_come_from_the_message_whatever_the_parse():
    instance = Instance.model_validate_json(Path("data/synthetic-cse-s0.json").read_text(encoding="utf-8"))
    corpus = load_jsonl(Path("data/requests.jsonl"), instance)
    held = [e for e in corpus if e.split in ("val", "test")]
    extra = distill.extra_denials(instance, 40, seed=1, exclude=held, near_miss=0.35)
    deny = PolicyOutput(verdict="forbidden", cited_rules=["P-LUNCH"], explanation="lunch")
    answers = {"P-LUNCH": deny.model_dump_json(), "P-MAXCONSEC": deny.model_copy(update={"cited_rules": ["P-MAXCONSEC"]}).model_dump_json(),
               "allowed": PolicyOutput(verdict="allowed", explanation="ok").model_dump_json()}
    rows, reasons = distill.denial_samples(extra, [corpus], instance, Path("data/handbook.md"), answers)
    assert rows and all(r["split"] == "train" and r["task"] == "policy" for r in rows)
    held_text = {e.request.raw_text for e in held}
    for r in rows:
        prompt, out = r["messages"][1]["content"], PolicyOutput.model_validate_json(r["messages"][2]["content"])
        assert distill._MESSAGE.search(prompt).group(1) not in held_text
        if out.verdict == "forbidden":  # the rule it cites was shown
            assert f"[{out.cited_rules[0]}]" in prompt.split("# Calendar")[0]
    shown = {k.split("(")[1] for k in reasons if "(" in k}
    assert {"gold parse)", "misread parse)", "none parse)"} <= shown
    assert any(k.startswith("allowed") for k in reasons)
