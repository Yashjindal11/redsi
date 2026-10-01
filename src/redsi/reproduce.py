"""Re-run a finding to measure how reproducible it is.

A finding stores the full test case (input, evaluator specs, relation) and a
:class:`~redsi.targets.TargetRef`, so it can be replayed without the
original campaign. Each attempt re-executes the test (and its parent, if the
test is relational) and re-evaluates it with the same evaluators.

Status updates are conservative: reproduction can *promote* a ``likely``
finding to ``confirmed`` (failed in at least two thirds of attempts), and it
marks findings that only sometimes fail as ``flaky``. It never deletes or
silently downgrades an observed deterministic failure.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from redsi._version import __version__
from redsi.campaign.artifact import RunArtifact
from redsi.campaign.config import CampaignConfig, Mode
from redsi.campaign.runner import CampaignRunner
from redsi.core.models import FindingStatus, Reproducibility, TestCase, Verdict, utcnow
from redsi.evaluators.base import Embedder
from redsi.findings.builder import AVAILABILITY
from redsi.providers import ModelRoles
from redsi.targets import Target, TargetAdapter

PROMOTE_AT = 2 / 3


class ReproductionResult(BaseModel):
    finding_id: str
    run_id: str
    attempts: int
    failures: int
    verdicts: list[str]
    outputs: list[str] = Field(default_factory=list)
    status_before: FindingStatus
    status_after: FindingStatus
    flaky: bool
    checked_at: datetime = Field(default_factory=utcnow)
    warnings: list[str] = Field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.failures / self.attempts if self.attempts else 0.0

    @property
    def reproduced(self) -> bool:
        return self.failures > 0


async def reproduce(
    artifact: RunArtifact,
    finding_id: str,
    *,
    target: TargetAdapter | None = None,
    attempts: int = 3,
    models: ModelRoles | None = None,
    embedder: Embedder | None = None,
    update: bool = True,
) -> ReproductionResult:
    finding = artifact.finding(finding_id)
    record = artifact.record(finding.case_id)
    warnings: list[str] = []
    if artifact.environment.get("redsi") != __version__:
        warnings.append(
            f"artifact was produced by RedSI {artifact.environment.get('redsi')}, reproducing with {__version__}"
        )
    owned = target is None
    tgt = target or Target.from_ref(artifact.target)
    original = CampaignConfig.model_validate(artifact.config)
    cfg = CampaignConfig(
        mode=Mode.CUSTOM,
        fuzz=False,
        timeout=original.timeout,
        retries=original.retries,
        concurrency=1,
        agreement_threshold=original.agreement_threshold,
    )
    chain: list[TestCase] = []
    case: TestCase | None = record.case
    while case is not None:
        chain.insert(0, case)
        parent_id = case.relation.case_id if case.relation else None
        case = artifact.record(parent_id).case if parent_id else None
        if len(chain) > 10:
            break

    verdicts: list[str] = []
    outputs: list[str] = []
    failures = 0
    try:
        for _ in range(attempts):
            runner = CampaignRunner(tgt, cfg, models=models, embedder=embedder)
            records = await runner.execute(chain)
            rec = records[-1]
            v = rec.assessment.verdict
            verdicts.append(v.value)
            out = rec.outputs[0] if rec.outputs else None
            outputs.append((out.text if out and out.ok else (out.error if out else "")) or "")
            failed = v == Verdict.FAIL or (finding.category == AVAILABILITY and v == Verdict.ERROR)
            failures += int(failed)
    finally:
        if owned:
            await tgt.aclose()

    before = finding.status
    after = before
    if before == FindingStatus.LIKELY and failures / attempts >= PROMOTE_AT:
        after = FindingStatus.CONFIRMED
    flaky = 0 < failures < attempts
    result = ReproductionResult(
        finding_id=finding.id,
        run_id=artifact.run_id,
        attempts=attempts,
        failures=failures,
        verdicts=verdicts,
        outputs=[o[:500] for o in outputs],
        status_before=before,
        status_after=after,
        flaky=flaky,
        warnings=warnings,
    )
    if update:
        prev = finding.reproducibility or Reproducibility()
        finding.reproducibility = Reproducibility(
            attempts=prev.attempts + attempts,
            failures=prev.failures + failures,
            checked_at=result.checked_at,
            flaky=flaky or prev.flaky,
        )
        finding.status = after
        if failures == 0:
            finding.notes.append(
                f"{result.checked_at:%Y-%m-%d}: did not reproduce in {attempts} attempts"
            )
    return result
