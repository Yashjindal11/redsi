"""Turn evaluated test records into findings."""

from __future__ import annotations

from redsi.core.models import (
    CaseRecord,
    EvaluationResult,
    Finding,
    FindingStatus,
    TargetOutput,
    Verdict,
    stable_hash,
)
from redsi.core.severity import SeverityPolicy
from redsi.core.taxonomy import get_category
from redsi.findings.rootcause import analyze

AVAILABILITY = "reliability.availability"


def fingerprint(case_id: str, category: str) -> str:
    """Stable across runs for the same test; used for regression tracking."""
    return stable_hash({"case": case_id, "category": category}, 16)


def finding_status(record: CaseRecord, likely_threshold: float) -> FindingStatus | None:
    a = record.assessment
    if a.verdict == Verdict.FAIL:
        if a.deterministic_failure:
            return FindingStatus.CONFIRMED
        return FindingStatus.LIKELY if a.confidence >= likely_threshold else FindingStatus.UNCERTAIN
    if a.verdict == Verdict.UNCERTAIN and any(r.verdict == Verdict.FAIL for r in record.results):
        # Only surface uncertainty when someone actually voted "fail".
        return FindingStatus.UNCERTAIN
    return None


def _title(category: str, prompt: str) -> str:
    short = " ".join(prompt.split())
    short = short if len(short) <= 70 else short[:67] + "..."
    return f"{category}: {short}"


def build_findings(
    records: list[CaseRecord],
    run_id: str,
    *,
    policy: SeverityPolicy | None = None,
    likely_threshold: float = 0.6,
    errors_as_findings: bool = True,
) -> list[Finding]:
    policy = policy or SeverityPolicy()
    by_id = {r.case.id: r for r in records}
    drafts: list[Finding] = []
    for rec in records:
        if rec.skipped_reason:
            continue
        case = rec.case
        category = case.category
        status = finding_status(rec, likely_threshold)
        failing: list[EvaluationResult] = [r for r in rec.results if r.verdict == Verdict.FAIL]
        all_errored = bool(rec.outputs) and all(not o.ok for o in rec.outputs)
        if status is None and errors_as_findings and all_errored:
            status, category = FindingStatus.CONFIRMED, AVAILABILITY
        if status is None:
            continue

        base = case.severity or get_category(category).default_severity
        if category == AVAILABILITY and case.category != AVAILABILITY:
            base = get_category(AVAILABILITY).default_severity
        severity = policy.resolve(base, category, case.tags, case.requirements)
        output = next(
            (o for o in rec.outputs if o.ok), rec.outputs[0] if rec.outputs else TargetOutput()
        )
        evidence = [e for r in failing for e in r.evidence][:8]
        if output.error:
            evidence.insert(0, f"target error: {output.error}")
        drafts.append(
            Finding(
                id="",
                fingerprint=fingerprint(case.id, category),
                run_id=run_id,
                case_id=case.id,
                category=category,
                severity=severity,
                status=status,
                confidence=1.0 if output.error else rec.assessment.confidence,
                title=_title(category, case.input.prompt),
                input=case.input,
                output=output,
                expected=case.expected_behavior or case.reference,
                explanation=rec.assessment.explanation or (output.error or ""),
                evidence=evidence,
                results=rec.results,
                hypotheses=analyze(rec, by_id),
                origin=case.origin,
                requirements=case.requirements,
                tags=case.tags,
            )
        )

    status_rank = {
        FindingStatus.CONFIRMED: 0,
        FindingStatus.LIKELY: 1,
        FindingStatus.UNCERTAIN: 2,
        FindingStatus.FALSE_POSITIVE: 3,
    }
    drafts.sort(key=lambda f: (-f.severity.rank, status_rank[f.status], f.category, f.case_id))
    for i, f in enumerate(drafts, 1):
        f.id = f"FINDING-{i:03d}"
    return drafts
