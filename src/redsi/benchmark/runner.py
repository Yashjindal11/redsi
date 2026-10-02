"""``redsi benchmark``: compare failure-discovery methods on planted faults.

Methods share the same target, seed tests and test budget, and are repeated
with different random seeds. Scoring uses the target's ground truth:

* **faults discovered** - planted faults that at least one failing test
  triggered (the headline metric);
* **precision** - failing tests in which some fault actually fired;
* **detection recall** - tests in which a fault fired that were flagged;
* **tests to first discovery** - efficiency.

LLM-based methods run only when a generator (and judge) model is configured;
otherwise they are reported as skipped, never estimated.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from redsi.benchmark.target import (
    FAULTS,
    PlantedFaultTarget,
    faults_fired,
    seed_tests,
    specification,
)
from redsi.campaign import CampaignConfig, CampaignRunner, RunArtifact
from redsi.core.models import CaseRecord, TestCase, Verdict
from redsi.generators.llm import GenerationRequest, LLMGenerator
from redsi.generators.mutations import DEFAULT_STRATEGIES
from redsi.providers import ModelRoles
from redsi.spec import SpecificationGenerator


class MethodScore(BaseModel):
    method: str
    repeat: int
    tests: int
    target_calls: int
    faults_discovered: list[str]
    true_positives: int
    false_positives: int
    missed: int
    first_discovery: dict[str, int] = Field(default_factory=dict)

    @property
    def precision(self) -> float | None:
        flagged = self.true_positives + self.false_positives
        return None if flagged == 0 else self.true_positives / flagged

    @property
    def detection_recall(self) -> float | None:
        fired = self.true_positives + self.missed
        return None if fired == 0 else self.true_positives / fired


def _failed(rec: CaseRecord) -> bool:
    if rec.verdict == Verdict.FAIL:
        return True
    return rec.verdict == Verdict.ERROR and bool(rec.outputs) and all(not o.ok for o in rec.outputs)


def score(method: str, repeat: int, art: RunArtifact) -> MethodScore:
    tp = fp = missed = 0
    discovered: dict[str, int] = {}
    executed = [r for r in art.cases if not r.skipped_reason]
    for i, rec in enumerate(executed, 1):
        fired = {f for o in rec.outputs for f in faults_fired(o)}
        if _failed(rec):
            if fired:
                tp += 1
                for f in fired:
                    discovered.setdefault(f, i)
            else:
                fp += 1
        elif fired:
            missed += 1
    return MethodScore(
        method=method,
        repeat=repeat,
        tests=len(executed),
        target_calls=art.metrics.target_calls,
        faults_discovered=sorted(discovered),
        true_positives=tp,
        false_positives=fp,
        missed=missed,
        first_discovery=discovered,
    )


CaseBuilder = Callable[[int, ModelRoles | None], Any]


def _fuzz(strategies: list[str], adaptive: bool, per_seed: int, rounds: int) -> dict[str, Any]:
    return {"strategies": strategies, "per_seed": per_seed, "rounds": rounds, "adaptive": adaptive}


async def _spec_cases(seed: int, models: ModelRoles | None) -> list[TestCase]:
    return await SpecificationGenerator().generate(specification(), models, seed=seed)


async def _llm_cases(seed: int, models: ModelRoles | None, budget: int) -> list[TestCase]:
    spec = specification()
    return await LLMGenerator().generate(
        GenerationRequest(
            description=f"{spec.system.name}: {spec.system.description}",
            categories=sorted({f.category for f in FAULTS}),
            count=budget,
            examples=[c.input.prompt for c in seed_tests()],
            seed=seed,
        ),
        models,
    )


async def run_benchmark(
    *,
    repeats: int = 3,
    budget: int = 120,
    per_seed: int = 3,
    max_rounds: int = 50,
    models: ModelRoles | None = None,
    methods: list[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run each method ``repeats`` times. Fuzzing methods keep generating rounds
    until they reach ``budget`` tests (or stop producing new ones), so methods
    are compared at equal test budgets wherever they can use the budget."""
    has_llm = bool(models and models.generator and models.judges)
    rounds = max_rounds
    plan: dict[str, tuple[str, dict[str, Any] | None]] = {
        "static": ("seeds", None),
        "random_fuzz": ("seeds", _fuzz(["random_chars"], False, per_seed, rounds)),
        "mutation_fuzz": ("seeds", _fuzz(list(DEFAULT_STRATEGIES), False, per_seed, rounds)),
        "adaptive_fuzz": ("seeds", _fuzz(list(DEFAULT_STRATEGIES), True, per_seed, rounds)),
        "spec_driven": ("spec", _fuzz(list(DEFAULT_STRATEGIES), True, per_seed, rounds)),
        "llm_generation": ("llm", None),
    }
    selected = methods or list(plan)
    scores: list[MethodScore] = []
    skipped: dict[str, str] = {}
    for name in selected:
        source, fuzz = plan[name]
        if source == "llm" and not has_llm:
            skipped[name] = "needs --generator and --judge models"
            continue
        for r in range(repeats):
            if progress:
                progress(f"{name} (repeat {r + 1}/{repeats})")
            if source == "seeds":
                cases = seed_tests()
            elif source == "spec":
                cases = await _spec_cases(r, models)
            else:
                cases = seed_tests() + await _llm_cases(r, models, budget - len(seed_tests()))
            cfg = CampaignConfig(
                mode="custom",
                fuzz=fuzz if fuzz is not None else False,
                max_cases=budget,
                seed=r,
                retries=0,
                errors_as_findings=True,
            )
            runner = CampaignRunner(PlantedFaultTarget(), cfg, models=models)
            art = await runner.run(cases)
            scores.append(score(name, r, art))
    return {
        "faults": [f.__dict__ for f in FAULTS],
        "config": {
            "repeats": repeats,
            "budget": budget,
            "per_seed": per_seed,
            "max_rounds": max_rounds,
        },
        "summary": summarise(scores),
        "runs": [
            s.model_dump() | {"precision": s.precision, "detection_recall": s.detection_recall}
            for s in scores
        ],
        "skipped": skipped,
    }


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "std": None, "min": None, "max": None}
    return {
        "mean": round(statistics.fmean(values), 4),
        "std": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def summarise(scores: list[MethodScore]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    total = len(FAULTS)
    for method in dict.fromkeys(s.method for s in scores):
        rows = [s for s in scores if s.method == method]
        per_fault = {
            f.id: sum(f.id in s.faults_discovered for s in rows) / len(rows) for f in FAULTS
        }
        firsts = [v for s in rows for v in s.first_discovery.values()]
        out[method] = {
            "repeats": len(rows),
            "faults_discovered": _stats([len(s.faults_discovered) for s in rows]),
            "discovery_rate": _stats([len(s.faults_discovered) / total for s in rows]),
            "tests": _stats([s.tests for s in rows]),
            "precision": _stats([s.precision for s in rows if s.precision is not None]),
            "detection_recall": _stats(
                [s.detection_recall for s in rows if s.detection_recall is not None]
            ),
            "tests_to_discovery": _stats([float(v) for v in firsts]),
            "per_fault_discovery_frequency": per_fault,
        }
    return out


def render_markdown(result: dict[str, Any]) -> str:
    cfg = result["config"]
    lines = [
        "# RedSI benchmark: planted-fault discovery",
        "",
        f"Synthetic target with {len(result['faults'])} planted faults; budget {cfg['budget']} tests per method; "
        f"{cfg['repeats']} repeats (seeds 0..{cfg['repeats'] - 1}). Results describe this synthetic target only.",
        "",
        "| Method | Faults found (mean ± sd) | Tests | Precision | Detection recall | Tests to discovery |",
        "|---|---|---|---|---|---|",
    ]

    def fmt(s: dict[str, float | None], pct: bool = False) -> str:
        if s["mean"] is None:
            return "-"
        m, sd = float(s["mean"]), float(s["std"] or 0)
        return f"{m:.0%} ± {sd:.0%}" if pct else f"{m:.1f} ± {sd:.1f}"

    for method, s in result["summary"].items():
        lines.append(
            f"| {method} | {fmt(s['faults_discovered'])} / {len(result['faults'])} | {fmt(s['tests'])} | "
            f"{fmt(s['precision'], True)} | {fmt(s['detection_recall'], True)} | {fmt(s['tests_to_discovery'])} |"
        )
    for method, why in result["skipped"].items():
        lines.append(f"| {method} | skipped: {why} | | | | |")
    lines += [
        "",
        "Per-fault discovery frequency (share of repeats):",
        "",
        "| Fault | " + " | ".join(result["summary"]) + " |",
    ]
    lines.append("|---|" + "---|" * len(result["summary"]))
    for f in result["faults"]:
        row = [
            f"{result['summary'][m]['per_fault_discovery_frequency'][f['id']]:.0%}"
            for m in result["summary"]
        ]
        lines.append(f"| {f['id']} ({f['category']}) | " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"
