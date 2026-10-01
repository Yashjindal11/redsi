"""Measure how far to trust an evaluator.

Compare evaluator verdicts with human labels (``calibrate``) or with each
other (``agreement``). Results feed back into evaluator choice and into the
confidence you place in a campaign's findings.
"""

from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping

from pydantic import BaseModel

from redsi.core.models import EvaluationResult, Verdict

_BINARY = (Verdict.PASS, Verdict.FAIL)


class CalibrationReport(BaseModel):
    n: int
    accuracy: float | None
    fail_precision: float | None
    fail_recall: float | None
    kappa: float | None
    abstained: int
    confusion: dict[str, int]


def cohen_kappa(a: list[Verdict], b: list[Verdict]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if expected == 1:
        return 1.0 if observed == 1 else None
    return (observed - expected) / (1 - expected)


def calibrate(predicted: Iterable[Verdict], human: Iterable[Verdict]) -> CalibrationReport:
    """Score evaluator verdicts against human labels (pass/fail only).

    Evaluator abstentions (uncertain/error/skip) are counted, not scored.
    """
    pairs = list(zip(predicted, human, strict=True))
    abstained = sum(1 for p, h in pairs if p not in _BINARY and h in _BINARY)
    scored = [(p, h) for p, h in pairs if p in _BINARY and h in _BINARY]
    confusion = Counter(f"{p.value}->{h.value}" for p, h in scored)
    n = len(scored)
    tp = confusion["fail->fail"]
    fp = confusion["fail->pass"]
    fn = confusion["pass->fail"]
    return CalibrationReport(
        n=n,
        accuracy=None if n == 0 else sum(p == h for p, h in scored) / n,
        fail_precision=None if tp + fp == 0 else tp / (tp + fp),
        fail_recall=None if tp + fn == 0 else tp / (tp + fn),
        kappa=cohen_kappa([p for p, _ in scored], [h for _, h in scored]),
        abstained=abstained,
        confusion=dict(confusion),
    )


def agreement(
    results_by_case: Mapping[str, list[EvaluationResult]],
) -> dict[str, dict[str, float | int | None]]:
    """Pairwise agreement and kappa between evaluators that voted on the same cases."""
    votes: dict[str, dict[str, Verdict]] = defaultdict(dict)
    for case_id, results in results_by_case.items():
        for r in results:
            if r.verdict in _BINARY:
                votes[r.evaluator][case_id] = r.verdict
    out: dict[str, dict[str, float | int | None]] = {}
    for a, b in itertools.combinations(sorted(votes), 2):
        shared = sorted(set(votes[a]) & set(votes[b]))
        if not shared:
            continue
        va = [votes[a][c] for c in shared]
        vb = [votes[b][c] for c in shared]
        out[f"{a} vs {b}"] = {
            "n": len(shared),
            "agreement": sum(x == y for x, y in zip(va, vb, strict=True)) / len(shared),
            "kappa": cohen_kappa(va, vb),
        }
    return out
