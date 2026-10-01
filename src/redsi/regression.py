"""Regression analysis between two runs and CI gates.

Runs are matched by test id (a content hash), so the comparison is exact for
tests both runs executed. Tests only one run executed are reported as added
or removed, never silently counted as passes or failures.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from redsi.campaign.artifact import RunArtifact
from redsi.core.models import CaseRecord, FindingStatus, Verdict
from redsi.core.severity import Severity


class CaseChange(BaseModel):
    case_id: str
    category: str
    prompt: str
    before: Verdict | None = None
    after: Verdict | None = None
    severity_before: Severity | None = None
    severity_after: Severity | None = None
    finding_after: str | None = None


class Comparison(BaseModel):
    baseline_run: str
    candidate_run: str
    pass_rate_before: float | None
    pass_rate_after: float | None
    shared: int
    added: int
    removed: int
    regressions: list[CaseChange] = Field(default_factory=list)
    resolved: list[CaseChange] = Field(default_factory=list)
    persistent: list[CaseChange] = Field(default_factory=list)
    new_failures: list[CaseChange] = Field(default_factory=list)
    newly_uncertain: list[CaseChange] = Field(default_factory=list)
    severity_changes: list[CaseChange] = Field(default_factory=list)
    findings_before: dict[str, int] = Field(default_factory=dict)
    findings_after: dict[str, int] = Field(default_factory=dict)
    coverage_before: float = 0.0
    coverage_after: float = 0.0
    categories_added: list[str] = Field(default_factory=list)
    categories_removed: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def pass_rate_delta(self) -> float | None:
        if self.pass_rate_before is None or self.pass_rate_after is None:
            return None
        return round(self.pass_rate_after - self.pass_rate_before, 4)


def _executed(art: RunArtifact) -> dict[str, CaseRecord]:
    return {r.case.id: r for r in art.cases if not r.skipped_reason}


def _failed(rec: CaseRecord) -> bool:
    return rec.verdict == Verdict.FAIL or (
        rec.verdict == Verdict.ERROR and bool(rec.outputs) and all(not o.ok for o in rec.outputs)
    )


def compare(baseline: RunArtifact, candidate: RunArtifact) -> Comparison:
    a, b = _executed(baseline), _executed(candidate)
    sev_a = {f.case_id: f.severity for f in baseline.findings}
    sev_b = {f.case_id: f.severity for f in candidate.findings}
    fid_b = {f.case_id: f.id for f in candidate.findings}

    def change(case_id: str) -> CaseChange:
        rec = b.get(case_id) or a[case_id]
        return CaseChange(
            case_id=case_id,
            category=rec.case.category,
            prompt=" ".join(rec.case.input.prompt.split())[:120],
            before=a[case_id].verdict if case_id in a else None,
            after=b[case_id].verdict if case_id in b else None,
            severity_before=sev_a.get(case_id),
            severity_after=sev_b.get(case_id),
            finding_after=fid_b.get(case_id),
        )

    cmp = Comparison(
        baseline_run=baseline.run_id,
        candidate_run=candidate.run_id,
        pass_rate_before=baseline.metrics.pass_rate,
        pass_rate_after=candidate.metrics.pass_rate,
        shared=len(set(a) & set(b)),
        added=len(set(b) - set(a)),
        removed=len(set(a) - set(b)),
        findings_before=baseline.metrics.findings_by_severity,
        findings_after=candidate.metrics.findings_by_severity,
        coverage_before=baseline.coverage.taxonomy_fraction,
        coverage_after=candidate.coverage.taxonomy_fraction,
    )
    for cid in sorted(set(a) & set(b)):
        fa, fb = _failed(a[cid]), _failed(b[cid])
        if not fa and fb:
            if a[cid].verdict == Verdict.PASS:
                cmp.regressions.append(change(cid))
            else:
                cmp.new_failures.append(change(cid))
        elif fa and not fb:
            if b[cid].verdict == Verdict.PASS:
                cmp.resolved.append(change(cid))
            else:
                cmp.newly_uncertain.append(change(cid))
        elif fa and fb:
            ch = change(cid)
            cmp.persistent.append(ch)
            if ch.severity_before != ch.severity_after:
                cmp.severity_changes.append(ch)
        elif a[cid].verdict == Verdict.PASS and b[cid].verdict == Verdict.UNCERTAIN:
            cmp.newly_uncertain.append(change(cid))
    for cid in sorted(set(b) - set(a)):
        if _failed(b[cid]):
            cmp.new_failures.append(change(cid))

    cats_a = {c for c, cell in baseline.coverage.categories.items() if cell.executed}
    cats_b = {c for c, cell in candidate.coverage.categories.items() if cell.executed}
    cmp.categories_added = sorted(cats_b - cats_a)
    cmp.categories_removed = sorted(cats_a - cats_b)

    if baseline.target.name != candidate.target.name:
        cmp.warnings.append(
            f"different targets: {baseline.target.name!r} vs {candidate.target.name!r}"
        )
    if baseline.environment.get("redsi") != candidate.environment.get("redsi"):
        cmp.warnings.append(
            "runs were produced by different RedSI versions; built-in tests may differ"
        )
    if cmp.shared == 0:
        cmp.warnings.append("no shared tests: runs are not comparable test-by-test")
    elif cmp.removed > cmp.shared:
        cmp.warnings.append(f"{cmp.removed} baseline tests were not executed in the candidate run")
    return cmp


class GateConfig(BaseModel):
    """CI thresholds. ``None`` disables a check."""

    max_critical: int | None = 0
    max_high: int | None = None
    min_pass_rate: float | None = Field(default=None, ge=0, le=1)
    max_regressions: int | None = 0
    max_new_failures: int | None = None
    count_statuses: list[FindingStatus] = Field(
        default_factory=lambda: [FindingStatus.CONFIRMED, FindingStatus.LIKELY],
        description="finding statuses that count toward severity thresholds",
    )


class GateResult(BaseModel):
    passed: bool
    violations: list[str] = Field(default_factory=list)
    checked: list[str] = Field(default_factory=list)


def evaluate_gate(
    candidate: RunArtifact, gate: GateConfig, comparison: Comparison | None = None
) -> GateResult:
    violations: list[str] = []
    checked: list[str] = []
    counted = [f for f in candidate.findings if f.status in gate.count_statuses]

    def count(sev: Severity) -> int:
        return sum(1 for f in counted if f.severity == sev)

    if gate.max_critical is not None:
        checked.append(f"critical findings <= {gate.max_critical}")
        if count(Severity.CRITICAL) > gate.max_critical:
            violations.append(f"{count(Severity.CRITICAL)} critical findings > {gate.max_critical}")
    if gate.max_high is not None:
        checked.append(f"high findings <= {gate.max_high}")
        if count(Severity.HIGH) > gate.max_high:
            violations.append(f"{count(Severity.HIGH)} high findings > {gate.max_high}")
    if gate.min_pass_rate is not None:
        checked.append(f"pass rate >= {gate.min_pass_rate:.0%}")
        rate = candidate.metrics.pass_rate
        if rate is None or rate < gate.min_pass_rate:
            shown = "n/a" if rate is None else f"{rate:.1%}"
            violations.append(f"pass rate {shown} < {gate.min_pass_rate:.0%}")
    if comparison is not None:
        if gate.max_regressions is not None:
            checked.append(f"regressions <= {gate.max_regressions}")
            if len(comparison.regressions) > gate.max_regressions:
                violations.append(
                    f"{len(comparison.regressions)} regressions > {gate.max_regressions}"
                )
        if gate.max_new_failures is not None:
            checked.append(f"new failures <= {gate.max_new_failures}")
            if len(comparison.new_failures) > gate.max_new_failures:
                violations.append(
                    f"{len(comparison.new_failures)} new failures > {gate.max_new_failures}"
                )
    return GateResult(passed=not violations, violations=violations, checked=checked)
