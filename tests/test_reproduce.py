from pathlib import Path

from redsi import CampaignConfig, RedSI, RunStore, Target, TestCase
from redsi.core.models import FindingStatus, Relation
from redsi.evaluators import ConsistentWithParent, LLMJudge, NumericAnswer
from redsi.providers import ScriptedProvider
from redsi.reproduce import reproduce

FIXTURE = str(Path(__file__).parent / "fixtures" / "toy_targets.py")
COUNTER = {"n": 0}


def flaky_math(prompt: str) -> str:
    COUNTER["n"] += 1
    return "4" if COUNTER["n"] % 2 else "5"


async def test_reproduce_rebuilds_importable_target_and_records_rate(tmp_path) -> None:
    case = TestCase(
        input="Say something",
        category="reasoning.arithmetic",
        reference="4",
        evaluators=[NumericAnswer()],
    )
    redsi = RedSI(Target.from_import(f"{FIXTURE}:echo"), store=tmp_path)
    art = await redsi.run(tests=[case], mode="custom")
    [f] = art.findings
    result = await reproduce(art, f.id, attempts=3)
    assert result.failures == 3 and result.rate == 1.0 and not result.flaky
    assert f.reproducibility and f.reproducibility.attempts == 3
    RunStore(tmp_path).update(art)
    assert RunStore(tmp_path).load(art.run_id).findings[0].reproducibility.attempts == 3


async def test_reproduce_detects_flaky_failures() -> None:
    COUNTER["n"] = 0
    case = TestCase(
        input="2+2?", category="reasoning.arithmetic", reference="4", evaluators=[NumericAnswer()]
    )
    target = Target.from_function(flaky_math)
    art = await RedSI(target, store=None).run(tests=[case], mode="custom")
    if not art.findings:  # first call happened to pass; force a failing run
        art = await RedSI(target, store=None).run(tests=[case], mode="custom")
    [f] = art.findings
    result = await reproduce(art, f.id, target=target, attempts=4)
    assert result.flaky and result.failures == 2
    assert f.status == FindingStatus.CONFIRMED  # deterministic failures are never downgraded


async def test_reproduce_promotes_likely_findings() -> None:
    judge = ScriptedProvider(['{"verdict": "fail", "confidence": 0.9}'])
    case = TestCase(
        input="q", category="factuality.hallucination", evaluators=[LLMJudge(rubric="r")]
    )
    redsi = RedSI(Target.from_function(lambda p: "made up"), judges=[judge], store=None)
    art = await redsi.run(tests=[case], config=CampaignConfig(mode="custom"))
    [f] = art.findings
    assert f.status == FindingStatus.LIKELY
    result = await reproduce(art, f.id, target=redsi.target, models=redsi.models, attempts=3)
    assert result.status_after == FindingStatus.CONFIRMED and f.status == FindingStatus.CONFIRMED


async def test_reproduce_reruns_parent_for_relational_tests() -> None:
    calls: list[str] = []

    def target(prompt: str) -> str:
        calls.append(prompt)
        return "100" if prompt == "parent" else "7"

    parent = TestCase(
        input="parent", category="robustness.paraphrase", evaluators=[{"type": "non_empty"}]
    )
    child = TestCase(
        input="child",
        category="robustness.paraphrase",
        relation=Relation(case_id=parent.id),
        evaluators=[ConsistentWithParent()],
    )
    t = Target.from_function(target)
    art = await RedSI(t, store=None).run(tests=[parent, child], mode="custom")
    f = next(f for f in art.findings if f.case_id == child.id)
    calls.clear()
    result = await reproduce(art, f.id, target=t, attempts=2)
    assert calls == ["parent", "child", "parent", "child"]
    assert result.failures == 2
