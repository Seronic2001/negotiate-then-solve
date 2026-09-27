"""Compiler training data: the gold JSON must mean exactly the corpus targets."""

import json

from core.generator import generate_department
from evaluation.metrics import exact_match
from language.compiler import completion, export, gold_output, user_message
from language.corpus import ExpectedAction, generate_corpus
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


def test_export_skips_post_parse_decisions_and_keeps_splits(tmp_path):
    instance = generate_department(seed=0)
    corpus = generate_corpus(instance, n=200, seed=0)
    counts = export([corpus], instance, tmp_path)
    kept = [ex for ex in corpus if ex.expected_action not in (ExpectedAction.DENY, ExpectedAction.REFUSE)]
    assert sum(counts.values()) == len(kept)
    rows = [json.loads(line) for line in (tmp_path / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    by_id = {ex.id: ex for ex in corpus}
    assert all(by_id[r["id"]].split == "train" for r in rows)
    assert [m["role"] for m in rows[0]["messages"]] == ["system", "user", "assistant"]
    assert "<message>" in user_message(instance, by_id[rows[0]["id"]].request)
