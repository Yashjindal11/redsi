"""AI fuzzing: apply mutation strategies to seed tests and learn which ones find failures.

Each generated test records its strategy chain in ``origin.strategies``.
After a round, :func:`strategy_stats` attributes failures to strategies, and
:func:`next_weights` turns those counts into sampling weights for the next
round (posterior mean of a Beta(1, 1) prior on each strategy's failure rate),
so budget shifts toward strategies that are finding failures while still
exploring the others.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from redsi.core.models import CaseRecord, TestCase, Verdict
from redsi.generators.mutations import DEFAULT_STRATEGIES, Mutation, build_strategies

if TYPE_CHECKING:
    from redsi.providers import ModelRoles


class FuzzConfig(BaseModel):
    strategies: list[str] = Field(default_factory=lambda: list(DEFAULT_STRATEGIES))
    per_seed: int = Field(default=2, ge=1, le=20)
    depth: int = Field(default=1, ge=1, le=4)
    rounds: int = Field(default=1, ge=1, le=10)
    adaptive: bool = True
    seed: int = 0


class Fuzzer:
    def __init__(
        self,
        strategies: Sequence[Mutation | str] | None = None,
        *,
        per_seed: int = 2,
        depth: int = 1,
        seed: int = 0,
        models: ModelRoles | None = None,
    ) -> None:
        resolved: list[Mutation] = []
        for s in strategies or build_strategies():
            resolved.extend(build_strategies([s]) if isinstance(s, str) else [s])
        self.strategies = resolved
        self.per_seed = per_seed
        self.depth = depth
        self.seed = seed
        self.models = models

    @classmethod
    def from_config(
        cls, config: FuzzConfig | dict[str, Any], models: ModelRoles | None = None
    ) -> Fuzzer:
        cfg = FuzzConfig.model_validate(config)
        return cls(
            cfg.strategies, per_seed=cfg.per_seed, depth=cfg.depth, seed=cfg.seed, models=models
        )

    async def generate(
        self,
        seeds: Iterable[TestCase],
        *,
        weights: dict[str, float] | None = None,
        round_index: int = 0,
    ) -> list[TestCase]:
        rng = random.Random(f"{self.seed}:{round_index}")
        frontier = list(seeds)
        seen = {c.id for c in frontier}
        out: list[TestCase] = []
        for _ in range(self.depth):
            next_frontier: list[TestCase] = []
            for seed_case in frontier:
                for strategy in self._pick(rng, weights):
                    variant = await strategy.mutate(seed_case, rng, self.models)
                    if variant is None or variant.id in seen:
                        continue
                    variant.origin = (
                        variant.origin.model_copy(update={"round": round_index})
                        if variant.origin
                        else None
                    )
                    seen.add(variant.id)
                    out.append(variant)
                    if variant.relation is not None:
                        # Only answer-preserving variants are mutated further.
                        next_frontier.append(variant)
            frontier = next_frontier
        return out

    def _pick(self, rng: random.Random, weights: dict[str, float] | None) -> list[Mutation]:
        k = min(self.per_seed, len(self.strategies))
        if not weights:
            return rng.sample(self.strategies, k)
        pool = list(self.strategies)
        chosen: list[Mutation] = []
        for _ in range(k):
            w = [max(weights.get(s.name, 0.5), 1e-6) for s in pool]
            pick = rng.choices(pool, weights=w, k=1)[0]
            chosen.append(pick)
            pool.remove(pick)
        return chosen


def strategy_stats(records: Iterable[CaseRecord]) -> dict[str, dict[str, Any]]:
    """Per-strategy yield. A strategy is credited for every test whose chain includes it."""
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"generated": 0, "executed": 0, "failed": 0, "uncertain": 0, "categories": set()}
    )
    for rec in records:
        if not rec.case.origin or not rec.case.origin.strategies:
            continue
        for s in set(rec.case.origin.strategies):
            row = stats[s]
            row["generated"] += 1
            if rec.skipped_reason:
                continue
            row["executed"] += 1
            if rec.verdict == Verdict.FAIL:
                row["failed"] += 1
                row["categories"].add(rec.case.category)
            elif rec.verdict == Verdict.UNCERTAIN:
                row["uncertain"] += 1
    out: dict[str, dict[str, Any]] = {}
    for name, row in sorted(stats.items()):
        executed = row["executed"]
        out[name] = {
            **{k: v for k, v in row.items() if k != "categories"},
            "failure_rate": round(row["failed"] / executed, 4) if executed else None,
            "failure_categories": sorted(row["categories"]),
        }
    return out


def next_weights(stats: dict[str, dict[str, Any]], strategies: Iterable[str]) -> dict[str, float]:
    return {
        s: (stats.get(s, {}).get("failed", 0) + 1) / (stats.get(s, {}).get("executed", 0) + 2)
        for s in strategies
    }
