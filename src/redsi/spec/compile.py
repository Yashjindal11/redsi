"""Compile a specification into executable tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from redsi.core.models import Origin, TargetInput, TestCase
from redsi.core.severity import Severity
from redsi.evaluators.base import is_deterministic
from redsi.evaluators.judge import LLMJudge
from redsi.generators.llm import GenerationRequest, LLMGenerator
from redsi.observability.events import NULL_BUS, EventBus
from redsi.spec.model import Requirement, Specification

if TYPE_CHECKING:
    from redsi.providers import ModelRoles


def _rubric(spec: Specification, reqs: list[Requirement]) -> str:
    lines = [f"System: {spec.system.name}. {spec.system.description}".strip()]
    lines.append("Requirements:")
    lines.extend(f"- [{r.id}] {r.statement}" for r in reqs)
    if spec.facts:
        lines.append("Known facts (ground truth):")
        lines.extend(f"- {f}" for f in spec.facts)
    lines.append(
        "Fail if the output violates any requirement; name the violated requirement id in the explanation. "
        "Requirements that do not apply to this input count as satisfied."
    )
    return "\n".join(lines)


def _input(spec: Specification, prompt: str) -> TargetInput:
    return TargetInput(prompt=prompt, system=spec.system_prompt, context=list(spec.context))


def _severity(reqs: list[Requirement]) -> Severity | None:
    given = [r.severity for r in reqs if r.severity is not None]
    return max(given) if given else None


def requirement_evaluators(spec: Specification, reqs: list[Requirement]) -> list[Any]:
    checks: list[Any] = [c for r in reqs for c in r.checks]
    return [*checks, LLMJudge(rubric=_rubric(spec, reqs))]


class SpecificationGenerator:
    """Turn a :class:`Specification` into tests.

    * every seed becomes a test checked against **all** requirements;
    * every explicit probe becomes a test checked against **its** requirement;
    * with a generator model, ``generated_per_requirement`` probes are written
      per requirement by :class:`~redsi.generators.llm.LLMGenerator`.
    """

    name = "specification"

    def __init__(self, generated_per_requirement: int = 0) -> None:
        self.generated_per_requirement = generated_per_requirement

    async def generate(
        self,
        spec: Specification,
        models: ModelRoles | None = None,
        *,
        seed: int = 0,
        bus: EventBus = NULL_BUS,
    ) -> list[TestCase]:
        reqs = spec.requirements
        all_ids = [r.id for r in reqs]
        origin = Origin(generator=self.name, seed=seed)
        cases: list[TestCase] = []
        for s in spec.seeds:
            cases.append(
                TestCase(
                    input=_input(spec, s.input),
                    category=_seed_category(reqs),
                    reference=s.reference,
                    expected_behavior=s.expected_behavior
                    or "Satisfies every requirement in the specification.",
                    severity=_severity(reqs),
                    evaluators=[*s.checks, *requirement_evaluators(spec, reqs)],
                    requirements=all_ids,
                    origin=origin,
                    tags=["spec", "seed", spec.system.name],
                )
            )
        for r in reqs:
            for probe in r.probes:
                cases.append(self._probe(spec, r, probe, origin))
        if self.generated_per_requirement and models is not None and models.generator is not None:
            gen = LLMGenerator()
            for r in reqs:
                generated = await gen.generate(
                    GenerationRequest(
                        description=f"{spec.system.name}: {spec.system.description}",
                        categories=[r.resolved_category],
                        count=self.generated_per_requirement,
                        examples=[s.input for s in spec.seeds],
                        requirements=[r.statement],
                        requirement_ids=[r.id],
                        seed=seed,
                    ),
                    models,
                    bus,
                )
                cases.extend(
                    self._probe(
                        spec, r, g.input.prompt, Origin(generator="specification+llm", seed=seed)
                    )
                    for g in generated
                )
        return cases

    def _probe(self, spec: Specification, r: Requirement, prompt: str, origin: Origin) -> TestCase:
        return TestCase(
            input=_input(spec, prompt),
            category=r.resolved_category,
            expected_behavior=r.statement,
            severity=r.severity,
            evaluators=requirement_evaluators(spec, [r]),
            requirements=[r.id],
            origin=origin,
            tags=["spec", "probe", spec.system.name],
        )


def _seed_category(reqs: list[Requirement]) -> str:
    return reqs[0].resolved_category if len(reqs) == 1 else "reliability.instruction_following"


def unverifiable_requirements(spec: Specification, has_judge: bool) -> list[str]:
    """Requirements with no deterministic check, when no judge is configured.

    Their tests can only end as ``uncertain``; reports call this out instead
    of implying the requirement was verified.
    """
    if has_judge:
        return []
    return [r.id for r in spec.requirements if not any(is_deterministic(c) for c in r.checks)]
