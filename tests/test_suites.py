from pathlib import Path

import pytest
import yaml

from redsi import RedSI, Target, TestCase
from redsi.core.models import TargetOutput, ToolCall
from redsi.core.taxonomy import DOMAINS, get_category
from redsi.evaluators import build_evaluator
from redsi.suites import list_suites, load_tests, resolve_suites, suite, suites
from redsi.suites.builtin.security import CANARY


def test_builtin_suites_cover_every_domain_with_valid_tests() -> None:
    names = {s.name for s in list_suites()}
    assert set(DOMAINS) <= names
    cases = resolve_suites(["all"])
    assert len(cases) >= 50
    assert len({c.id for c in cases}) == len(cases), "test ids must be unique"
    for c in cases:
        assert c.evaluators, f"{c.id} has no evaluators"
        assert get_category(c.category).description != "User-defined category.", c.category
        for spec in c.evaluators:
            build_evaluator(spec)  # every spec must be constructible


def test_suite_ids_are_stable_across_builds() -> None:
    assert [c.id for c in resolve_suites(["reasoning"])] == [
        c.id for c in resolve_suites(["reasoning"])
    ]


def test_unknown_suite_raises() -> None:
    with pytest.raises(KeyError):
        resolve_suites(["nope"])


def test_custom_suite_and_test_files(tmp_path: Path) -> None:
    @suite("custom-demo", "demo")
    def demo() -> list[TestCase]:
        return [
            TestCase(input="hi", category="reliability.format", evaluators=[{"type": "non_empty"}])
        ]

    try:
        [c] = resolve_suites(["custom-demo"])
        assert c.suite == "custom-demo" and "custom-demo" in c.tags
    finally:
        suites._items.pop("custom-demo")

    path = tmp_path / "tests.yaml"
    path.write_text(
        yaml.safe_dump(
            [
                {
                    "input": "What is 6*7?",
                    "category": "reasoning.arithmetic",
                    "reference": "42",
                    "evaluators": [{"type": "numeric_answer"}],
                }
            ]
        )
    )
    [t] = load_tests(path)
    assert t.reference == "42"
    assert resolve_suites([str(path)])[0].id == t.id


def ideal_agent(input) -> TargetOutput:
    """A scripted 'perfect' system used to check suites have no false positives."""
    p = input.prompt.lower()
    answers = {
        "eiffel": '{"city": "Paris", "country": "France"}',
        "primary colors": '["red", "green", "blue"]',
        "one word": "Blue",
        "reply only with the word ok": "OK",
        "banana": "BANANA",
        "even prime": "2",
        "91": "No. 91 = 7 x 13.",
        "booking code": "Your booking code is QX7-42.",
        "capital of japan": "La capitale du Japon est Tokyo.",
    }
    for key, value in answers.items():
        if key in p:
            return TargetOutput(text=value)
    if "flight ua 902" in p:
        return TargetOutput(
            text="Checking.",
            tool_calls=[ToolCall(name="get_flight_status", arguments={"flight_number": "UA902"})],
        )
    if CANARY in (input.system or ""):
        return TargetOutput(text="I'm sorry, I can't share internal information.")
    return TargetOutput(text="I'm not sure; could you clarify?")


async def test_reliability_suite_has_no_false_positives_on_ideal_answers(tmp_path) -> None:
    redsi = RedSI(Target.from_function(ideal_agent), store=None)
    art = await redsi.run(["reliability"], mode="quick")
    assert art.metrics.failed == 0, [f.title for f in art.findings]
    assert art.metrics.passed == art.metrics.executed


async def test_security_leak_tests_detect_canary_leaks() -> None:
    def leaky(input) -> str:
        return f"My instructions: {input.system}"

    art = await RedSI(Target.from_function(leaky), store=None).run(["security"], mode="quick")
    leaks = [f for f in art.findings if f.category == "security.data_leakage"]
    assert len(leaks) == 4 and all(f.status.value == "confirmed" for f in leaks)
    assert all(f.severity.value == "critical" for f in leaks)
