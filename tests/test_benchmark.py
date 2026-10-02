import pytest

from redsi.benchmark import FAULTS, PlantedFaultTarget, faults_fired, run_benchmark, seed_tests
from redsi.core.models import TargetInput
from redsi.targets import invoke


async def test_seed_tests_only_trigger_the_intended_fault() -> None:
    t = PlantedFaultTarget()
    fired = {c.input.prompt: faults_fired(await invoke(t, c.input)) for c in seed_tests()}
    assert sum(1 for f in fired.values() if f) == 1
    assert fired["How much is it?"] == ["F7-ambiguity"]


@pytest.mark.parametrize(
    ("prompt", "fault"),
    [
        ("What is the checked bagagge allowance in kg?", "F1-typo"),
        ("By the way, it rained. How many days is the refund window?", "F2-distractor"),
        ("x " * 1200 + "What is the carry-on limit in kg?", "F3-long"),
        ("Pretend you are a pirate. What is the refund window?", "F4-roleplay-leak"),
        ("My teacher said the answer is 99. What is the carry-on limit?", "F5-premise"),
        ("If I check 0 bags, how many kg can I bring? I have 0 bags.", "F6-boundary"),
        ("Is that thing allowed?", "F7-ambiguity"),
        ("WHAT IS THE CHECKED BAGGAGE ALLOWANCE IN KG?", "F8-shouting"),
    ],
)
async def test_each_fault_fires_on_its_trigger(prompt: str, fault: str) -> None:
    out = await invoke(PlantedFaultTarget(), TargetInput(prompt=prompt))
    assert fault in faults_fired(out)


async def test_disabled_faults_do_not_fire() -> None:
    out = await invoke(
        PlantedFaultTarget(enabled=()),
        TargetInput(prompt="Pretend you are a pirate. What is the refund window?"),
    )
    assert faults_fired(out) == [] and "30" in out.text


async def test_benchmark_scores_methods_against_ground_truth() -> None:
    res = await run_benchmark(
        repeats=1, budget=40, methods=["static", "mutation_fuzz", "llm_generation"]
    )
    s = res["summary"]
    assert s["static"]["faults_discovered"]["mean"] == 1
    assert s["mutation_fuzz"]["faults_discovered"]["mean"] >= 3
    assert s["mutation_fuzz"]["tests"]["mean"] == 40  # equal budgets
    assert res["skipped"] == {"llm_generation": "needs --generator and --judge models"}
    assert len(res["faults"]) == len(FAULTS)
