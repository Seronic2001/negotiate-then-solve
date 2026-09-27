"""Paraphrase checks, with a stub in place of the LLM."""

import pytest

from core.generator import generate_department
from language.corpus import INJECTIONS, generate_corpus
from language.paraphrase import (
    FidelityCheck,
    paraphrase_corpus,
    split_injection,
)


@pytest.fixture(scope="module")
def instance():
    return generate_department(seed=0)


@pytest.fixture(scope="module")
def check(instance):
    return FidelityCheck(instance)


def test_same_facts_pass(check):
    orig = "I'm at a conference in week 7, Tuesday to Thursday."
    assert check.problems(orig, "conf in wk 7, tues-thurs, sorry", "F-101") == []
    assert check.problems("no classes before 10 am", "nothing before 10:00 please", "F-101") == []


def test_every_day_name_is_recognised(check):
    full = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday"
    assert check.days(full) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    assert check.days("Wednesdays, Tues, thurs") == {"wed", "tue", "thu"}
    assert check.problems("on Monday and Wednesday", "on Monday", "F-101")


def test_changed_facts_fail(check):
    orig = "I'm at a conference in week 7, Tuesday to Thursday."
    assert check.problems(orig, "I'm at a conference in week 8, Tuesday to Thursday.", "F-101")
    assert check.problems(orig, "I'm at a conference in week 7, Tuesday to Friday.", "F-101")
    assert check.problems(orig, "I'm at a conference in the seventh week, Tuesday to Thursday.", "F-101")


def test_entities(instance, check):
    other, own = instance.faculty[3], instance.faculty[4]
    orig = f"Please move {other.name}'s Monday class.\n\nRegards,\n{own.name}"
    assert check.problems(orig, f"pls move {other.name.replace('.', '')}'s monday class", own.id) == []
    assert check.problems(orig, "pls move my monday class", own.id)
    lab = next(r for r in instance.rooms if r.type.value == "lab")
    assert check.problems(f"{lab.name} is closed in week 5.", "The lab is closed in week 5.", "S-LAB")


def test_split_injection():
    body, suffix = split_injection("Please move it.\n" + INJECTIONS[0])
    assert body == "Please move it." and suffix == "\n" + INJECTIONS[0]
    assert split_injection("no injection here") == ("no injection here", "")


class _Echo:
    """Pretends to paraphrase: lowercases, but breaks every third item."""

    class _Client:
        model = "stub"
        usage = type("U", (), {})()

    def __init__(self):
        self.client = self._Client()
        self.calls = 0

    def batch(self, items):
        self.calls += 1
        return {i: (t.lower() if n % 3 or self.calls > 1 else t + " week 99") for n, (i, _, t) in enumerate(items)}


def test_paraphrase_corpus_keeps_labels_and_injections(instance):
    corpus = generate_corpus(instance, n=60, seed=0)
    out, report = paraphrase_corpus(corpus, instance, _Echo(), batch_size=10, workers=1)
    assert report["paraphrased"] == 60 and not report["kept_template"]
    for old, new in zip(corpus, out, strict=True):
        assert new.targets == old.targets and new.expected_action == old.expected_action
        assert new.template_text == old.request.raw_text
        if old.injection:
            assert any(new.request.raw_text.endswith(inj) for inj in INJECTIONS)
    assert all(ex.template_text is None for ex in corpus)  # input untouched
