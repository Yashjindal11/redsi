"""The run artifact: one self-contained, machine-readable record of a campaign."""

from __future__ import annotations

import contextlib
import importlib.metadata
import platform
import secrets
import sys
from collections import Counter
from datetime import datetime
from statistics import mean, quantiles
from typing import Any

from pydantic import BaseModel, Field

from redsi._version import __version__
from redsi.core.models import CaseRecord, Finding, Usage, Verdict, utcnow
from redsi.coverage import Coverage
from redsi.targets.base import TargetRef

SCHEMA_VERSION = 1


def new_run_id() -> str:
    return f"RUN-{utcnow():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def environment() -> dict[str, Any]:
    pkgs = {}
    for name in ("pydantic", "httpx"):
        with contextlib.suppress(importlib.metadata.PackageNotFoundError):
            pkgs[name] = importlib.metadata.version(name)
    return {
        "redsi": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": pkgs,
    }


class Metrics(BaseModel):
    total: int = 0
    executed: int = 0
    passed: int = 0
    failed: int = 0
    uncertain: int = 0
    errors: int = 0
    skipped: int = 0
    pass_rate: float | None = None
    findings_by_severity: dict[str, int] = Field(default_factory=dict)
    findings_by_status: dict[str, int] = Field(default_factory=dict)
    findings_by_category: dict[str, int] = Field(default_factory=dict)
    disagreements: int = 0
    target_calls: int = 0
    target_usage: Usage = Field(default_factory=Usage)
    evaluator_usage: Usage = Field(default_factory=Usage)
    latency_ms_mean: float | None = None
    latency_ms_p50: float | None = None
    latency_ms_p95: float | None = None
    duration_s: float = 0.0

    @property
    def total_cost_usd(self) -> float | None:
        costs = [
            u.cost_usd for u in (self.target_usage, self.evaluator_usage) if u.cost_usd is not None
        ]
        return sum(costs) if costs else None


def compute_metrics(
    records: list[CaseRecord], findings: list[Finding], evaluator_usage: Usage, duration_s: float
) -> Metrics:
    m = Metrics(
        total=len(records), evaluator_usage=evaluator_usage, duration_s=round(duration_s, 3)
    )
    latencies: list[float] = []
    usage = Usage()
    for rec in records:
        if rec.skipped_reason:
            m.skipped += 1
            continue
        m.executed += 1
        v = rec.assessment.verdict
        if v == Verdict.PASS:
            m.passed += 1
        elif v == Verdict.FAIL:
            m.failed += 1
        elif v == Verdict.ERROR:
            m.errors += 1
        else:
            m.uncertain += 1
        m.disagreements += int(rec.assessment.disagreement)
        for out in rec.outputs:
            m.target_calls += 1
            if out.latency_ms is not None:
                latencies.append(out.latency_ms)
            if out.usage is not None:
                usage = usage + out.usage
    m.target_usage = usage
    judged = m.passed + m.failed + m.uncertain
    # Uncertain counts against the pass rate: unverified is not passed.
    m.pass_rate = round(m.passed / judged, 4) if judged else None
    m.findings_by_severity = dict(Counter(f.severity.value for f in findings))
    m.findings_by_status = dict(Counter(f.status.value for f in findings))
    m.findings_by_category = dict(Counter(f.category for f in findings))
    if latencies:
        m.latency_ms_mean = round(mean(latencies), 2)
        if len(latencies) >= 2:
            qs = quantiles(latencies, n=20, method="inclusive")
            m.latency_ms_p50, m.latency_ms_p95 = round(qs[9], 2), round(qs[18], 2)
        else:
            m.latency_ms_p50 = m.latency_ms_p95 = round(latencies[0], 2)
    return m


class RunArtifact(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    name: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    environment: dict[str, Any] = Field(default_factory=environment)
    target: TargetRef
    models: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    spec: dict[str, Any] | None = None
    cases: list[CaseRecord] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    metrics: Metrics = Field(default_factory=Metrics)
    coverage: Coverage = Field(default_factory=Coverage)
    fuzz: dict[str, Any] | None = None
    stopped_reason: str | None = None

    def finding(self, finding_id: str) -> Finding:
        for f in self.findings:
            if f.id == finding_id or f.fingerprint == finding_id:
                return f
        raise KeyError(f"{finding_id} not found in {self.run_id}")

    def record(self, case_id: str) -> CaseRecord:
        for r in self.cases:
            if r.case.id == case_id:
                return r
        raise KeyError(f"test {case_id} not found in {self.run_id}")

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "target": self.target.name,
            "tests": self.metrics.total,
            "passed": self.metrics.passed,
            "failed": self.metrics.failed,
            "pass_rate": self.metrics.pass_rate,
            "findings": self.metrics.findings_by_severity,
        }
