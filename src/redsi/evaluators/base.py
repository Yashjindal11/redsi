"""Evaluator interface.

Evaluators are pydantic models so their parameters serialise into an
:class:`~redsi.core.models.EvaluatorSpec`; a stored finding can therefore be
re-evaluated later. Register custom evaluators with :func:`register`::

    @register("starts_with")
    class StartsWith(OutputEvaluator):
        prefix: str

        def check(self, case, output):
            ok = output.text.startswith(self.prefix)
            return self.passed() if ok else self.failed(f"does not start with {self.prefix!r}")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict

from redsi.core.models import (
    EvaluationResult,
    EvaluatorSpec,
    TargetOutput,
    TestCase,
    Usage,
    Verdict,
)
from redsi.core.registry import Registry
from redsi.observability.events import NULL_BUS, EventBus

if TYPE_CHECKING:
    from redsi.providers import ModelRoles

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]


@dataclass
class EvalContext:
    """What an evaluator may look at besides the test and its outputs."""

    outputs_by_case: dict[str, list[TargetOutput]] = field(default_factory=dict)
    cases_by_id: dict[str, TestCase] = field(default_factory=dict)
    models: ModelRoles | None = None
    embedder: Embedder | None = None
    bus: EventBus = NULL_BUS
    usage: Usage = field(default_factory=Usage)

    def add_usage(self, usage: Usage | None) -> None:
        if usage is not None:
            self.usage = self.usage + usage


class Evaluator(BaseModel, ABC):
    model_config = ConfigDict(extra="forbid")

    type: ClassVar[str] = "evaluator"
    deterministic: ClassVar[bool] = True

    @abstractmethod
    async def evaluate(
        self, case: TestCase, outputs: list[TargetOutput], ctx: EvalContext
    ) -> EvaluationResult | list[EvaluationResult]:
        """Judge the outputs of one test. May return one result per voter."""

    def to_spec(self) -> EvaluatorSpec:
        return EvaluatorSpec(
            type=self.type, params=self.model_dump(mode="json", exclude_defaults=True)
        )

    def label(self) -> str:
        """Name shown in results and reports."""
        return self.type

    # Helpers so subclasses stay short.
    def _result(self, verdict: Verdict, explanation: str = "", **kw: Any) -> EvaluationResult:
        kw.setdefault("deterministic", self.deterministic)
        kw.setdefault("evaluator", self.label())
        return EvaluationResult(verdict=verdict, explanation=explanation, **kw)

    def passed(self, explanation: str = "", **kw: Any) -> EvaluationResult:
        return self._result(Verdict.PASS, explanation, **kw)

    def failed(self, explanation: str, **kw: Any) -> EvaluationResult:
        return self._result(Verdict.FAIL, explanation, **kw)

    def uncertain(self, explanation: str, **kw: Any) -> EvaluationResult:
        return self._result(Verdict.UNCERTAIN, explanation, **kw)

    def skipped(self, explanation: str) -> EvaluationResult:
        return self._result(Verdict.SKIP, explanation, confidence=0.0)


class OutputEvaluator(Evaluator):
    """Checks each sample independently; the test fails if any sample fails."""

    @abstractmethod
    def check(self, case: TestCase, output: TargetOutput) -> EvaluationResult: ...

    async def evaluate(
        self, case: TestCase, outputs: list[TargetOutput], ctx: EvalContext
    ) -> EvaluationResult:
        usable = [o for o in outputs if o.ok]
        if not usable:
            return self.skipped("no successful target output to evaluate")
        results = [self.check(case, o) for o in usable]
        failures = [(i, r) for i, r in enumerate(results) if r.verdict == Verdict.FAIL]
        if not failures:
            uncertain = [r for r in results if r.verdict == Verdict.UNCERTAIN]
            return uncertain[0] if uncertain else results[0]
        i, first = failures[0]
        if len(results) > 1:
            first.evidence.append(f"failed on {len(failures)}/{len(results)} samples (first: #{i})")
            first.score = 1 - len(failures) / len(results)
        return first


EvaluatorType = type[Evaluator]
E = TypeVar("E", bound=EvaluatorType)
evaluators: Registry[EvaluatorType] = Registry("evaluator", "redsi.evaluators")


def register(name: str) -> Callable[[E], E]:
    def wrap(cls: E) -> E:
        cls.type = name
        evaluators.register(name, cls)
        return cls

    return wrap


def build_evaluator(spec: EvaluatorSpec | dict[str, Any] | Evaluator) -> Evaluator:
    if isinstance(spec, Evaluator):
        return spec
    spec = EvaluatorSpec.model_validate(spec)
    return evaluators.get(spec.type)(**spec.params)


def is_deterministic(spec: EvaluatorSpec) -> bool:
    """Whether the evaluator type named by ``spec`` is deterministic (unknown -> False)."""
    try:
        return bool(evaluators.get(spec.type).deterministic)
    except KeyError:
        return False
