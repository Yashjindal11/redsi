"""Resilience and determinism properties (judge caching, generator outages, isolation)."""

import random

from redsi import CampaignConfig, Target, TestCase
from redsi.campaign import CampaignRunner
from redsi.core.models import TargetOutput
from redsi.evaluators import EvalContext, LLMJudge
from redsi.evaluators.judge import build_judge_prompt
from redsi.generators import GenerationRequest, LLMGenerator, mutations
from redsi.observability import EventBus, MemorySink
from redsi.observability.events import NULL_BUS
from redsi.providers import CachedProvider, ModelRoles, ScriptedProvider


class Broken(ScriptedProvider):
    async def complete(self, request):  # type: ignore[override]
        raise RuntimeError("provider down")


def test_judge_prompt_is_deterministic_so_judge_calls_can_be_cached() -> None:
    case = TestCase(input="q", category="x.y")
    out = TargetOutput(text="answer")
    assert build_judge_prompt("r", case, out, True) == build_judge_prompt("r", case, out, True)
    assert build_judge_prompt("r", case, out, True) != build_judge_prompt(
        "r", case, TargetOutput(text="other"), True
    )


async def test_judge_cache_hits_on_identical_evaluations(tmp_path) -> None:
    judge = CachedProvider(ScriptedProvider(['{"verdict": "pass", "confidence": 0.9}']), tmp_path)
    ctx = EvalContext(models=ModelRoles(judges=[judge]))
    case = TestCase(input="q", category="x.y")
    for _ in range(2):
        await LLMJudge(rubric="r").evaluate(case, [TargetOutput(text="a")], ctx)
    assert judge.hits == 1


async def test_generator_failures_do_not_abort() -> None:
    sink = MemorySink()
    cases = await LLMGenerator().generate(
        GenerationRequest(description="x", categories=["reasoning.logic"], count=3),
        ModelRoles(generator=Broken([])),
        EventBus([sink]),
    )
    assert cases == [] and sink.of_type("error")
    seed = TestCase(
        input="What is the capital of France?", category="x.y", evaluators=[{"type": "non_empty"}]
    )
    variant = await mutations.get("paraphrase")().mutate(
        seed, random.Random(0), ModelRoles(generator=Broken([]))
    )
    assert variant is not None  # fell back to templates


async def test_runner_does_not_mutate_shared_null_bus() -> None:
    before = NULL_BUS.run_id
    runner = CampaignRunner(Target.from_function(lambda p: "x"), CampaignConfig(mode="custom"))
    await runner.run([TestCase(input="q", category="x.y", evaluators=[{"type": "non_empty"}])])
    assert NULL_BUS.run_id == before
