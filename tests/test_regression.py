from redsi import RedSI, Target, TestCase
from redsi.core.models import FindingStatus
from redsi.evaluators import NotContains, NumericAnswer
from redsi.regression import GateConfig, compare, evaluate_gate

CASES = [
    TestCase(
        input="2+2?", category="reasoning.arithmetic", reference="4", evaluators=[NumericAnswer()]
    ),
    TestCase(
        input="3*3?", category="reasoning.arithmetic", reference="9", evaluators=[NumericAnswer()]
    ),
    TestCase(
        input="leak?", category="security.data_leakage", evaluators=[NotContains(texts=["CANARY"])]
    ),
]


def v1(prompt: str) -> str:
    return {"2+2?": "4", "3*3?": "10", "leak?": "no"}[prompt]


def v2(prompt: str) -> str:
    return {"2+2?": "5", "3*3?": "9", "leak?": "CANARY"}[prompt]


async def runs():
    a = await RedSI(Target.from_function(v1, name="bot"), store=None).run(
        tests=CASES, mode="custom"
    )
    b = await RedSI(Target.from_function(v2, name="bot"), store=None).run(
        tests=CASES, mode="custom"
    )
    return a, b


async def test_compare_classifies_changes() -> None:
    a, b = await runs()
    cmp = compare(a, b)
    assert cmp.shared == 3 and cmp.added == 0 and cmp.removed == 0
    assert {c.prompt for c in cmp.regressions} == {"2+2?", "leak?"}
    assert [c.prompt for c in cmp.resolved] == ["3*3?"]
    assert cmp.pass_rate_before == round(2 / 3, 4) and cmp.pass_rate_after == round(1 / 3, 4)
    assert cmp.pass_rate_delta is not None and cmp.pass_rate_delta < 0
    assert cmp.findings_after.get("critical") == 1
    assert not cmp.warnings


async def test_gate_fails_on_critical_and_regressions() -> None:
    a, b = await runs()
    cmp = compare(a, b)
    result = evaluate_gate(b, GateConfig(min_pass_rate=0.9), cmp)
    assert not result.passed
    assert any("critical" in v for v in result.violations)
    assert any("regressions" in v for v in result.violations)
    assert any("pass rate" in v for v in result.violations)
    assert evaluate_gate(a, GateConfig(max_critical=0, max_regressions=None)).passed


async def test_gate_ignores_uncertain_and_false_positive_findings_by_default() -> None:
    _, b = await runs()
    for f in b.findings:
        f.status = FindingStatus.FALSE_POSITIVE
    assert evaluate_gate(b, GateConfig()).passed


async def test_compare_warns_when_runs_do_not_overlap() -> None:
    a, _ = await runs()
    other = await RedSI(Target.from_function(lambda p: "x", name="other"), store=None).run(
        tests=[
            TestCase(
                input="new",
                category="x.y",
                evaluators=[{"type": "contains", "params": {"all_of": ["y"]}}],
            )
        ],
        mode="custom",
    )
    cmp = compare(a, other)
    assert cmp.shared == 0 and cmp.added == 1 and cmp.removed == 3
    assert len(cmp.new_failures) == 1
    assert any("no shared tests" in w for w in cmp.warnings)
    assert any("different targets" in w for w in cmp.warnings)
