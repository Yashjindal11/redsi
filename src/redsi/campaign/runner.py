"""Campaign execution engine.

Tests run in *waves*: a test whose ``relation`` points at another test runs
after it, so relational evaluators can see the original output. Within a
wave, tests run concurrently under a global limit. Budgets (target calls,
cost) and early stopping are enforced between target calls; tests that do
not run are recorded as skipped with a reason, never silently dropped.
"""

from __future__ import annotations

import asyncio
import fnmatch
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from redsi.campaign.artifact import RunArtifact, compute_metrics, new_run_id
from redsi.campaign.config import CampaignConfig
from redsi.core.models import (
    Assessment,
    CaseRecord,
    EvaluationResult,
    TargetOutput,
    TestCase,
    Verdict,
    utcnow,
)
from redsi.coverage import compute_coverage
from redsi.evaluators.aggregate import aggregate
from redsi.evaluators.base import Embedder, EvalContext, build_evaluator
from redsi.findings.builder import build_findings
from redsi.observability.events import NULL_BUS, EventBus, EventType
from redsi.providers import ModelRoles
from redsi.targets.base import TargetAdapter, invoke

_RETRYABLE = (
    "timeout",
    "HTTP 429",
    "HTTP 5",
    "ConnectError",
    "ReadError",
    "RemoteProtocolError",
    "transport",
)


def is_retryable(output: TargetOutput) -> bool:
    return bool(output.error) and any(s in (output.error or "") for s in _RETRYABLE)


def select_cases(cases: Iterable[TestCase], config: CampaignConfig) -> list[TestCase]:
    """Deduplicate and filter tests; keep the first occurrence of each id."""
    seen: set[str] = set()
    out: list[TestCase] = []
    for case in cases:
        if case.id in seen:
            continue
        if config.categories and not any(
            fnmatch.fnmatchcase(case.category, p) for p in config.categories
        ):
            continue
        if config.tags and not set(config.tags) & set(case.tags):
            continue
        if config.samples is not None:
            case = case.model_copy(update={"samples": config.samples})
        seen.add(case.id)
        out.append(case)
    return out


def plan_waves(cases: list[TestCase]) -> list[list[TestCase]]:
    by_id = {c.id: c for c in cases}
    depth: dict[str, int] = {}

    def d(case: TestCase, trail: frozenset[str] = frozenset()) -> int:
        if case.id in depth:
            return depth[case.id]
        parent = by_id.get(case.relation.case_id) if case.relation else None
        value = 0 if parent is None or parent.id in trail else d(parent, trail | {case.id}) + 1
        depth[case.id] = value
        return value

    waves: dict[int, list[TestCase]] = {}
    for c in cases:
        waves.setdefault(d(c), []).append(c)
    return [waves[k] for k in sorted(waves)]


@dataclass
class _State:
    target_calls: int = 0
    cost: float = 0.0
    failures: int = 0
    stopped: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class CampaignRunner:
    def __init__(
        self,
        target: TargetAdapter,
        config: CampaignConfig | None = None,
        *,
        models: ModelRoles | None = None,
        embedder: Embedder | None = None,
        bus: EventBus | None = None,
        run_id: str | None = None,
    ) -> None:
        self.target = target
        self.config = (config or CampaignConfig()).resolved()
        self.models = models
        self.run_id = run_id or new_run_id()
        self.bus = bus or NULL_BUS
        if self.bus.run_id is None:
            self.bus.run_id = self.run_id
        self.ctx = EvalContext(models=models, embedder=embedder, bus=self.bus)
        self._state = _State()

    async def run(
        self,
        cases: Iterable[TestCase],
        *,
        name: str | None = None,
        spec: dict[str, object] | None = None,
        requirement_ids: list[str] | None = None,
    ) -> RunArtifact:
        cfg = self.config
        started = time.perf_counter()
        created = utcnow()
        selected = select_cases(cases, cfg)
        records: list[CaseRecord] = []
        if cfg.max_cases is not None and len(selected) > cfg.max_cases:
            for c in selected[cfg.max_cases :]:
                records.append(_skipped(c, f"over max_cases={cfg.max_cases}"))
            selected = selected[: cfg.max_cases]
        self.ctx.cases_by_id = {c.id: c for c in selected}
        self.bus.emit(
            EventType.CAMPAIGN_STARTED,
            target=self.target.name,
            tests=len(selected),
            mode=cfg.mode.value,
        )
        sem = asyncio.Semaphore(cfg.concurrency)
        for wave in plan_waves(selected):
            results = await asyncio.gather(*(self._run_case(c, sem) for c in wave))
            records.extend(results)

        findings = build_findings(
            records,
            self.run_id,
            policy=cfg.severity,
            likely_threshold=cfg.likely_threshold,
            errors_as_findings=cfg.errors_as_findings,
        )
        for f in findings:
            self.bus.emit(
                EventType.FINDING,
                id=f.id,
                category=f.category,
                severity=f.severity.value,
                status=f.status.value,
            )
        duration = time.perf_counter() - started
        artifact = RunArtifact(
            run_id=self.run_id,
            name=name,
            created_at=created,
            finished_at=utcnow(),
            target=self.target.ref(),
            models=self.models.describe() if self.models else {},
            config=cfg.model_dump(mode="json"),
            spec=spec,
            cases=records,
            findings=findings,
            metrics=compute_metrics(records, findings, self.ctx.usage, duration),
            coverage=compute_coverage(records, requirement_ids),
            stopped_reason=self._state.stopped,
        )
        self.bus.emit(
            EventType.CAMPAIGN_FINISHED,
            passed=artifact.metrics.passed,
            failed=artifact.metrics.failed,
            findings=len(findings),
            duration_s=round(duration, 3),
            stopped_reason=self._state.stopped,
        )
        return artifact

    # ------------------------------------------------------------------ cases

    async def _run_case(self, case: TestCase, sem: asyncio.Semaphore) -> CaseRecord:
        missing = self.target.missing_capabilities(case.input)
        if missing:
            reason = f"target does not accept: {', '.join(sorted(missing))}"
            self.bus.emit(EventType.CASE_SKIPPED, case_id=case.id, reason=reason)
            return _skipped(case, reason)
        async with sem:
            if self._state.stopped:
                return _skipped(case, self._state.stopped)
            self.bus.emit(EventType.CASE_STARTED, case_id=case.id, category=case.category)
            start = time.perf_counter()
            outputs: list[TargetOutput] = []
            for i in range(case.samples):
                if not await self._reserve_call():
                    break
                outputs.append(await self._call(case, i))
            if not outputs:
                return _skipped(case, self._state.stopped or "budget exhausted")
            self.ctx.outputs_by_case[case.id] = outputs
            results, assessment = await self._evaluate(case, outputs)
            record = CaseRecord(
                case=case,
                outputs=outputs,
                results=results,
                assessment=assessment,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        await self._after_case(record)
        return record

    async def _reserve_call(self) -> bool:
        cfg = self.config
        async with self._state.lock:
            if self._state.stopped:
                return False
            if (
                cfg.max_target_calls is not None
                and self._state.target_calls >= cfg.max_target_calls
            ):
                self._stop(
                    f"max_target_calls={cfg.max_target_calls} reached", EventType.BUDGET_EXHAUSTED
                )
                return False
            spent = self._state.cost + (self.ctx.usage.cost_usd or 0.0)
            if cfg.max_cost_usd is not None and spent >= cfg.max_cost_usd:
                self._stop(f"max_cost_usd={cfg.max_cost_usd} reached", EventType.BUDGET_EXHAUSTED)
                return False
            self._state.target_calls += 1
            return True

    def _stop(self, reason: str, event: EventType) -> None:
        if not self._state.stopped:
            self._state.stopped = reason
            self.bus.emit(event, reason=reason)

    async def _call(self, case: TestCase, sample: int) -> TargetOutput:
        attempt = 0
        while True:
            output = await invoke(self.target, case.input, timeout=self.config.timeout)
            self.bus.emit(
                EventType.TARGET_CALL,
                case_id=case.id,
                sample=sample,
                latency_ms=output.latency_ms,
                error=output.error,
                tokens=output.usage.total_tokens if output.usage else None,
            )
            for call in output.tool_calls:
                self.bus.emit(
                    EventType.TOOL_CALL, case_id=case.id, tool=call.name, error=call.error
                )
            if output.usage and output.usage.cost_usd:
                async with self._state.lock:
                    self._state.cost += output.usage.cost_usd
            if not is_retryable(output) or attempt >= self.config.retries:
                return output
            attempt += 1
            self.bus.emit(EventType.RETRY, case_id=case.id, attempt=attempt, error=output.error)
            await asyncio.sleep(min(0.25 * 2**attempt, 5.0))

    async def _evaluate(
        self, case: TestCase, outputs: list[TargetOutput]
    ) -> tuple[list[EvaluationResult], Assessment]:
        if all(not o.ok for o in outputs):
            return [], Assessment(
                verdict=Verdict.ERROR,
                confidence=1.0,
                explanation=f"target error: {outputs[0].error}",
            )
        results: list[EvaluationResult] = []
        for spec in case.evaluators:
            try:
                evaluator = build_evaluator(spec)
                value = await evaluator.evaluate(case, outputs, self.ctx)
                batch = value if isinstance(value, list) else [value]
            except Exception as exc:
                batch = [
                    EvaluationResult(
                        evaluator=spec.type,
                        verdict=Verdict.ERROR,
                        confidence=0.0,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                ]
            for r in batch:
                self.bus.emit(
                    EventType.EVALUATION,
                    case_id=case.id,
                    evaluator=r.evaluator,
                    verdict=r.verdict.value,
                    confidence=r.confidence,
                )
            results.extend(batch)
        return results, aggregate(results, agreement_threshold=self.config.agreement_threshold)

    async def _after_case(self, record: CaseRecord) -> None:
        self.bus.emit(
            EventType.CASE_FINISHED,
            case_id=record.case.id,
            category=record.case.category,
            verdict=record.assessment.verdict.value,
            duration_ms=record.duration_ms,
        )
        if record.assessment.verdict == Verdict.FAIL:
            async with self._state.lock:
                self._state.failures += 1
                limit = self.config.max_failures
                if limit is not None and self._state.failures >= limit:
                    self._stop(f"max_failures={limit} reached", EventType.EARLY_STOP)


def _skipped(case: TestCase, reason: str) -> CaseRecord:
    return CaseRecord(
        case=case,
        assessment=Assessment(verdict=Verdict.SKIP, confidence=0.0, explanation=reason),
        skipped_reason=reason,
    )


__all__ = ["CampaignRunner", "is_retryable", "plan_waves", "select_cases"]
