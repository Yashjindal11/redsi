import random

import pytest

from redsi import CampaignConfig, Target, TestCase
from redsi.campaign import CampaignRunner
from redsi.core.models import Document, TargetInput
from redsi.evaluators import NumericAnswer
from redsi.fuzzing import Fuzzer, next_weights, strategy_stats
from redsi.generators import (
    DEFAULT_STRATEGIES,
    GenerationRequest,
    LLMGenerator,
    build_strategies,
    mutations,
)
from redsi.providers import ModelRoles, ScriptedProvider

SEED = TestCase(
    input="A train travels 180 kilometres in 2.5 hours. What is its average speed in km/h?",
    category="factuality.calculation",
    reference="72",
    evaluators=[NumericAnswer()],
)


@pytest.mark.parametrize("name", DEFAULT_STRATEGIES)
async def test_every_strategy_produces_a_valid_variant_with_lineage(name: str) -> None:
    [strategy] = build_strategies([name])
    variant = await strategy.mutate(SEED, random.Random(1))
    assert variant is not None
    assert variant.id != SEED.id
    assert (
        variant.origin
        and variant.origin.strategies == [name]
        and variant.origin.parent_id == SEED.id
    )
    assert variant.evaluators, "variants must be evaluable"
    if variant.relation is not None:
        # Answer-preserving: keeps the deterministic check and reference.
        assert variant.reference == "72"
        assert {e.type for e in variant.evaluators} >= {"numeric_answer"}
    else:
        assert variant.reference is None


async def test_mutations_are_deterministic_given_seed() -> None:
    a = await Fuzzer(seed=7).generate([SEED])
    b = await Fuzzer(seed=7).generate([SEED])
    c = await Fuzzer(seed=8).generate([SEED])
    assert [x.id for x in a] == [x.id for x in b]
    assert [x.id for x in a] != [x.id for x in c]


async def test_context_noise_adds_document_for_rag_inputs() -> None:
    rag = TestCase(
        input=TargetInput(prompt="q?", context=[Document(content="fact")]),
        category="rag.grounding",
        evaluators=[{"type": "non_empty"}],
    )
    v = await mutations.get("context_noise")().mutate(rag, random.Random(0))
    assert v is not None and len(v.input.context) == 2 and v.input.prompt == "q?"


async def test_paraphrase_uses_generator_model_when_available() -> None:
    gen = ScriptedProvider(
        ['{"paraphrase": "How fast, on average, is a train covering 180 kilometres in 2.5 hours?"}']
    )
    v = await mutations.get("paraphrase")().mutate(
        SEED, random.Random(0), ModelRoles(generator=gen)
    )
    assert v is not None and v.input.prompt.startswith("How fast")


async def test_depth_chains_strategies() -> None:
    variants = await Fuzzer(["paraphrase", "noise"], per_seed=2, depth=2).generate([SEED])
    assert any(len(v.origin.strategies) == 2 for v in variants if v.origin)


def correct_unless_distracted(prompt: str) -> str:
    # Toy target with a planted weakness: distractor text breaks it.
    if (
        "By the way" in prompt
        or "Unrelated" in prompt
        or "FYI" in prompt
        or "octopus" in prompt
        or "Note:" in prompt
        or "(" in prompt
    ):
        return "About 60 km/h."
    return "72 km/h."


async def test_campaign_fuzzing_attributes_failures_to_strategies() -> None:
    runner = CampaignRunner(
        Target.from_function(correct_unless_distracted),
        CampaignConfig(
            mode="custom",
            fuzz={
                "strategies": ["context_noise", "noise", "paraphrase"],
                "per_seed": 3,
                "rounds": 2,
            },
        ),
    )
    art = await runner.run([SEED])
    assert art.fuzz is not None
    stats = art.fuzz["strategies"]
    assert stats["context_noise"]["failed"] >= 1
    assert stats["noise"]["failed"] == 0
    f = next(f for f in art.findings if f.origin and "context_noise" in f.origin.strategies)
    assert any(h.cause.value == "model_limitation" for h in f.hypotheses)


def test_next_weights_prefers_productive_strategies() -> None:
    w = next_weights(
        {"a": {"failed": 4, "executed": 5}, "b": {"failed": 0, "executed": 5}}, ["a", "b", "c"]
    )
    assert w["a"] > w["c"] > w["b"]


def test_strategy_stats_ignores_unmutated_tests() -> None:
    assert strategy_stats([]) == {}


async def test_llm_generator_builds_judged_tests() -> None:
    gen = ScriptedProvider(
        [
            '{"tests": [{"input": "Can I bring a 40kg bag?", "expected_behavior": "Explain the 32kg limit."}]}'
        ]
    )
    cases = await LLMGenerator().generate(
        GenerationRequest(
            description="Airline baggage assistant", categories=["reasoning.edge_case"], count=1
        ),
        ModelRoles(generator=gen),
    )
    [c] = cases
    assert c.origin and c.origin.generator == "llm"
    assert c.evaluators[0].type == "llm_judge"
    with pytest.raises(RuntimeError):
        await LLMGenerator().generate(GenerationRequest(description="x", categories=["x.y"]), None)
