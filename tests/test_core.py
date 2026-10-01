import pytest

from redsi.core import (
    EvaluatorSpec,
    Severity,
    SeverityPolicy,
    SeverityRule,
    TargetInput,
    TestCase,
    Usage,
    categories,
    get_category,
)
from redsi.core.taxonomy import DOMAINS, Category, register_category


def test_testcase_accepts_string_input_and_gets_stable_id() -> None:
    a = TestCase(input="What is 2+2?", category="reasoning.arithmetic", reference="4")
    b = TestCase(input="What is 2+2?", category="reasoning.arithmetic", reference="4")
    assert a.input.prompt == "What is 2+2?"
    assert a.id == b.id
    assert a.id.startswith("T-")


def test_testcase_id_changes_with_identity_but_not_metadata() -> None:
    a = TestCase(input="q", category="x.y", metadata={"note": 1})
    b = TestCase(input="q", category="x.y", metadata={"note": 2})
    c = TestCase(input="q", category="x.z")
    assert a.id == b.id
    assert a.id != c.id


def test_testcase_coerces_objects_with_to_spec() -> None:
    class Fake:
        def to_spec(self) -> EvaluatorSpec:
            return EvaluatorSpec(type="contains", params={"text": "4"})

    case = TestCase(input="q", category="x.y", evaluators=[Fake()])
    assert case.evaluators[0].type == "contains"


def test_testcase_roundtrips_json() -> None:
    case = TestCase(input="q", category="x.y", tags=["a"], severity=Severity.HIGH)
    again = TestCase.model_validate_json(case.model_dump_json())
    assert again == case


def test_required_capabilities_and_render() -> None:
    ti = TargetInput(prompt="q", system="be nice", context=[{"content": "doc"}])
    assert ti.required_capabilities() == {"text", "system", "context"}
    rendered = ti.render_text()
    assert "be nice" in rendered and "doc" in rendered and rendered.endswith("q")


def test_usage_addition_keeps_unknown_cost_unknown() -> None:
    assert (Usage(prompt_tokens=1) + Usage(completion_tokens=2)).cost_usd is None
    total = Usage(prompt_tokens=1, cost_usd=0.5) + Usage(completion_tokens=2)
    assert total.total_tokens == 3 and total.cost_usd == 0.5


def test_severity_ordering() -> None:
    assert Severity.CRITICAL > Severity.HIGH > Severity.MEDIUM > Severity.LOW > Severity.INFO
    assert max([Severity.LOW, Severity.HIGH]) is Severity.HIGH


def test_severity_policy_first_match_wins() -> None:
    policy = SeverityPolicy(
        rules=[
            SeverityRule(category="security.*", severity=Severity.CRITICAL),
            SeverityRule(tags=["cosmetic"], severity=Severity.INFO),
        ]
    )
    assert policy.resolve(Severity.LOW, "security.data_leakage") is Severity.CRITICAL
    assert policy.resolve(Severity.HIGH, "robustness.noise", ["cosmetic"]) is Severity.INFO
    assert policy.resolve(Severity.MEDIUM, "reasoning.logic") is Severity.MEDIUM


def test_taxonomy_covers_all_domains() -> None:
    assert {c.domain for c in categories()} == set(DOMAINS)
    assert get_category("unknown.thing").description == "User-defined category."


def test_register_category_validates() -> None:
    with pytest.raises(ValueError):
        register_category(Category("nodot", "bad"))
    with pytest.raises(ValueError):
        register_category(Category("reasoning.logic", "dup"))
