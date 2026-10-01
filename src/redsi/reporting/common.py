"""Shared report content, independent of output format."""

from __future__ import annotations

from collections import Counter
from typing import Any

from redsi.campaign.artifact import RunArtifact
from redsi.core.models import Finding, FindingStatus
from redsi.core.severity import Severity
from redsi.core.taxonomy import get_category

SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]
ACTIONABLE = (FindingStatus.CONFIRMED, FindingStatus.LIKELY)


def executive_summary(art: RunArtifact) -> list[str]:
    m = art.metrics
    sev = m.findings_by_severity
    lines = [
        f"RedSI executed {m.executed} of {m.total} tests against `{art.target.name}`: "
        f"{m.passed} passed, {m.failed} failed, {m.uncertain} uncertain, {m.errors} errored"
        + (f", {m.skipped} skipped." if m.skipped else "."),
    ]
    if m.pass_rate is not None:
        lines.append(f"Pass rate: {m.pass_rate:.1%} (uncertain results count as not passed).")
    actionable = [f for f in art.findings if f.status in ACTIONABLE]
    if art.findings:
        parts = [f"{sev[s.value]} {s.value}" for s in SEVERITY_ORDER if sev.get(s.value)]
        lines.append(
            f"{len(art.findings)} findings ({', '.join(parts)}); "
            f"{len(actionable)} confirmed or likely, {len(art.findings) - len(actionable)} need review."
        )
    else:
        lines.append("No findings.")
    if art.stopped_reason:
        lines.append(f"The campaign stopped early: {art.stopped_reason}.")
    if art.spec and art.spec.get("unverifiable"):
        lines.append(
            f"{len(art.spec['unverifiable'])} specification requirements had no deterministic check "
            "and no judge model, so they could not be verified."
        )
    lines.append(
        "These results describe the behaviour observed on these tests only. "
        "They are not evidence that the system is safe or reliable in general."
    )
    return lines


def recommendations(art: RunArtifact) -> list[tuple[str, str, int]]:
    """(category, guidance, count) for categories with actionable findings."""
    counts = Counter(f.category for f in art.findings if f.status in ACTIONABLE)
    out = []
    for cat, n in counts.most_common():
        guidance = get_category(cat).recommendation
        if guidance:
            out.append((cat, guidance, n))
    return out


def reproduction_command(art: RunArtifact, f: Finding) -> str:
    return f"redsi reproduce {f.id} --run {art.run_id}"


def failure_distribution(art: RunArtifact) -> list[dict[str, Any]]:
    rows = []
    for cat, cell in art.coverage.categories.items():
        if cell.executed:
            rows.append(
                {
                    "category": cat,
                    "executed": cell.executed,
                    "failed": cell.failed,
                    "uncertain": cell.uncertain,
                    "rate": cell.failed / cell.executed,
                }
            )
    return sorted(rows, key=lambda r: (-r["failed"], r["category"]))


def fmt_usd(value: float | None) -> str:
    return "unknown (no pricing configured)" if value is None else f"${value:.4f}"
