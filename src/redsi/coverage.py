"""Evaluation coverage.

These are *evaluation coverage* metrics: which parts of the failure
taxonomy, specification, input space and mutation strategies a campaign
actually exercised. They say nothing about how safe a system is.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable

from pydantic import BaseModel, Field

from redsi.core.models import CaseRecord, Verdict
from redsi.core.taxonomy import DOMAINS, categories

DISCLAIMER = (
    "Evaluation coverage describes what was tested, not how safe the system is. "
    "Untested behaviours may still fail."
)


class Cell(BaseModel):
    executed: int = 0
    passed: int = 0
    failed: int = 0
    uncertain: int = 0
    errors: int = 0
    skipped: int = 0

    def add(self, record: CaseRecord) -> None:
        if record.skipped_reason:
            self.skipped += 1
            return
        self.executed += 1
        v = record.assessment.verdict
        if v == Verdict.PASS:
            self.passed += 1
        elif v == Verdict.FAIL:
            self.failed += 1
        elif v == Verdict.ERROR:
            self.errors += 1
        else:
            self.uncertain += 1


class Coverage(BaseModel):
    categories: dict[str, Cell] = Field(default_factory=dict)
    domains: dict[str, dict[str, int]] = Field(default_factory=dict)
    taxonomy_fraction: float = 0.0
    strategies: dict[str, Cell] = Field(default_factory=dict)
    requirements: dict[str, Cell] = Field(default_factory=dict)
    requirements_total: int | None = None
    capabilities: dict[str, int] = Field(default_factory=dict)
    input_lengths: dict[str, int] = Field(default_factory=dict)
    tools_called: dict[str, int] = Field(default_factory=dict)
    disclaimer: str = DISCLAIMER

    @property
    def requirement_fraction(self) -> float | None:
        if not self.requirements_total:
            return None
        tested = sum(1 for c in self.requirements.values() if c.executed)
        return tested / self.requirements_total


def _length_bucket(n: int) -> str:
    if n < 100:
        return "<100"
    if n < 1_000:
        return "100-1k"
    if n < 10_000:
        return "1k-10k"
    return ">10k"


def compute_coverage(
    records: Iterable[CaseRecord], requirement_ids: Iterable[str] | None = None
) -> Coverage:
    cats: dict[str, Cell] = defaultdict(Cell)
    strategies: dict[str, Cell] = defaultdict(Cell)
    reqs: dict[str, Cell] = defaultdict(Cell)
    caps: Counter[str] = Counter()
    lengths: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    req_ids = list(requirement_ids) if requirement_ids is not None else None
    for req in req_ids or []:
        reqs[req]

    for rec in records:
        case = rec.case
        cats[case.category].add(rec)
        chain = case.origin.strategies if case.origin and case.origin.strategies else ["(none)"]
        for s in chain:
            strategies[s].add(rec)
        for r in case.requirements:
            reqs[r].add(rec)
        if rec.skipped_reason:
            continue
        caps.update(case.input.required_capabilities())
        size = len(case.input.prompt) + sum(len(d.content) for d in case.input.context)
        lengths[_length_bucket(size)] += 1
        for out in rec.outputs:
            tools.update(c.name for c in out.tool_calls)

    builtin = categories()
    tested = {c for c, cell in cats.items() if cell.executed}
    domains = {
        d: {
            "categories_total": sum(1 for c in builtin if c.domain == d),
            "categories_tested": sum(1 for c in builtin if c.domain == d and c.id in tested),
        }
        for d in DOMAINS
    }
    return Coverage(
        categories=dict(sorted(cats.items())),
        domains=domains,
        taxonomy_fraction=round(sum(1 for c in builtin if c.id in tested) / len(builtin), 4),
        strategies=dict(sorted(strategies.items())),
        requirements=dict(sorted(reqs.items())),
        requirements_total=len(req_ids) if req_ids is not None else None,
        capabilities=dict(caps),
        input_lengths=dict(lengths),
        tools_called=dict(tools),
    )
