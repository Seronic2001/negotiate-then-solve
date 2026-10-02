"""Compiler training data: the gold JSON must mean exactly the corpus targets."""

import json

from core.generator import generate_department
from evaluation.metrics import exact_match
from language.compiler import completion, export, gold_output, user_message
from language.corpus import (
    FULL_DAY,
    ExpectedAction,
    core_text,
    duplicates_held_out,
    extra_denials,
    extra_parser_examples,
    generate_corpus,
    held_out,
)
from language.parsing import ParseOutput, postprocess


def test_gold_json_round_trips_to_the_targets():
    instance = generate_department(seed=0)
    for ex in generate_corpus(instance, n=200, seed=0):
        if ex.expected_action != ExpectedAction.COMPILE:
            continue
        out = ParseOutput.model_validate_json(completion(gold_output(ex)))
        result = postprocess(instance, ex.request, out)
        assert result.action == ExpectedAction.COMPILE, ex.id
        assert exact_match(result.constraints, ex.targets, instance), ex.id


def test_export_skips_refusals_keeps_denials_and_splits(tmp_path):
    instance = generate_department(seed=0)
    corpus = generate_corpus(instance, n=200, seed=0)
    counts = export([corpus], instance, tmp_path)
    held = held_out([corpus])
    kept = [ex for ex in corpus if ex.expected_action != ExpectedAction.REFUSE
            and (ex.expected_action != ExpectedAction.DENY or gold_output(ex, instance) is not None)
            and not duplicates_held_out(ex.request.raw_text, ex.split, held)]
    assert any(ex.expected_action == ExpectedAction.DENY for ex in kept)
    assert sum(n for k, n in counts.items() if k in ("train", "val", "test")) == len(kept)
    rows = [json.loads(line) for line in (tmp_path / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    by_id = {ex.id: ex for ex in corpus}
    assert all(by_id[r["id"]].split == "train" for r in rows)
    assert [m["role"] for m in rows[0]["messages"]] == ["system", "user", "assistant"]
    assert "<message>" in user_message(instance, by_id[rows[0]["id"]].request)


def test_denials_parse_to_what_the_rule_forbids():
    """A rule-breaking request compiles to the constraint it asks for; the policy agent denies it later."""
    instance = generate_department(seed=0)
    lunch, limit = instance.calendar.lunch_slot, instance.policy.max_consecutive
    corpus = generate_corpus(instance, n=400, seed=0)
    denials = [ex for ex in corpus if ex.expected_action == ExpectedAction.DENY]
    denials += extra_denials(instance, 60, seed=1)
    for ex in denials:
        out = gold_output(ex, instance)
        assert out is not None and out.action == "compile", ex.id
        result = postprocess(instance, ex.request, out)
        assert result.action == ExpectedAction.COMPILE and not result.errors, (ex.id, result.errors)
        slots = [s for c in result.constraints for s in (c.when.slots or [])]
        assert lunch in slots if ex.violates_rule == "P-LUNCH" else len(slots) > limit, ex.id


def test_extra_denials_stay_clear_of_held_out_requests():
    instance = generate_department(seed=0)
    corpus = generate_corpus(instance, n=600, seed=0)
    held = [ex for ex in corpus if ex.split in ("val", "test")]
    extra = extra_denials(instance, 100, seed=1, exclude=held)
    assert len(extra) == 100 and {ex.split for ex in extra} == {"train"}
    assert {ex.violates_rule for ex in extra} == {"P-LUNCH", "P-MAXCONSEC"}
    held_text = {ex.request.raw_text for ex in held}
    for ex in extra:
        assert ex.request.raw_text not in held_text
        day = FULL_DAY[ex.targets[0].when.days[0]]
        assert not any(h.violates_rule == ex.violates_rule and h.request.sender_id == ex.request.sender_id
                       and day in h.request.raw_text for h in held), ex.id


def test_near_misses_are_legal_look_alikes():
    instance = generate_department(seed=0)
    lunch, limit = instance.calendar.lunch_slot, instance.policy.max_consecutive
    extra = extra_denials(instance, 120, seed=2, near_miss=0.5)
    legal = [ex for ex in extra if ex.expected_action == ExpectedAction.COMPILE]
    assert 30 < len(legal) < 90
    for ex in legal:
        slots = ex.targets[0].when.slots
        assert lunch not in slots and len(slots) <= limit and not ex.rules, ex.id


def test_training_never_repeats_a_held_out_request(tmp_path):
    """Greeting and sign-off aside, no train or val row repeats a request of a later split."""
    instance = generate_department(seed=0)
    corpus = generate_corpus(instance, n=600, seed=0)
    export([corpus], instance, tmp_path)
    held = held_out([corpus])
    for split in ("train", "val"):
        for line in (tmp_path / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            message = json.loads(line)["messages"][1]["content"].split("<message>\n")[1].split("\n</message>")[0]
            assert not duplicates_held_out(message, split, held), message
    assert core_text("Hello,\nWho approves X? Thanks.\n\nRegards,\nDr. Rao") == core_text("who approves x?")


def test_extra_parser_examples_are_new_and_labelled():
    instance = generate_department(seed=0)
    corpus = generate_corpus(instance, n=600, seed=0)
    extra = extra_parser_examples(instance, seed=2, exclude=corpus, answer=30, out_of_scope=32, clarify=12)
    by = {a: [e for e in extra if e.expected_action.value == a] for a in ("answer", "out_of_scope", "clarify")}
    assert [len(by[a]) for a in by] == [30, 32, 12]
    old = {core_text(e.request.raw_text) for e in corpus}
    cores = [core_text(e.request.raw_text) for e in extra]
    assert len(set(cores)) == len(cores) and not set(cores) & old
    assert all(e.split == "train" for e in extra) and all(e.rules for e in by["answer"])
    for ex in extra:
        out = gold_output(ex, instance)
        assert out.action == ex.expected_action.value
        assert postprocess(instance, ex.request, out).action == ex.expected_action, ex.id
    assert all(gold_output(e, instance).missing for e in by["clarify"])
