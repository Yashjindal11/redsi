"""Combine evaluator results into one :class:`Assessment`.

Rules (see docs/evaluation.md):

1. A deterministic failure decides the test: ``fail`` with that evaluator's
   confidence. Non-deterministic passes do not override it, but a confident
   dissenting pass is recorded as disagreement.
2. Otherwise non-deterministic results vote, weighted by confidence.
   Deterministic passes do not vote: a regex passing says nothing about the
   property a judge was asked to assess.
3. If the winning side's share of weight is below ``agreement_threshold``,
   the verdict is ``uncertain``.
4. With only deterministic passes, the test passes.
"""

from __future__ import annotations

from statistics import mean

from redsi.core.models import Assessment, EvaluationResult, Verdict


def aggregate(results: list[EvaluationResult], *, agreement_threshold: float = 0.67) -> Assessment:
    active = [r for r in results if r.verdict != Verdict.SKIP]
    if not active:
        reasons = "; ".join(r.explanation for r in results if r.explanation) or "no evaluators"
        return Assessment(
            verdict=Verdict.UNCERTAIN, confidence=0.0, explanation=f"nothing evaluated ({reasons})"
        )

    det_fail = [r for r in active if r.deterministic and r.verdict == Verdict.FAIL]
    nondet = [
        r
        for r in active
        if not r.deterministic and r.verdict in (Verdict.PASS, Verdict.FAIL, Verdict.UNCERTAIN)
    ]
    if det_fail:
        strongest = max(det_fail, key=lambda r: r.confidence)
        dissent = [r for r in nondet if r.verdict == Verdict.PASS and r.confidence >= 0.7]
        return Assessment(
            verdict=Verdict.FAIL,
            confidence=strongest.confidence,
            deterministic_failure=True,
            disagreement=bool(dissent),
            agreement=None,
            explanation=f"{strongest.evaluator}: {strongest.explanation}",
        )

    if not nondet:
        det_pass = [r for r in active if r.deterministic and r.verdict == Verdict.PASS]
        if det_pass:
            return Assessment(
                verdict=Verdict.PASS,
                confidence=min(r.confidence for r in det_pass),
                explanation="all deterministic checks passed",
            )
        errors = [r for r in active if r.verdict == Verdict.ERROR]
        return Assessment(
            verdict=Verdict.ERROR,
            confidence=0.0,
            explanation="; ".join(f"{r.evaluator}: {r.error or r.explanation}" for r in errors),
        )

    weight = {Verdict.PASS: 0.0, Verdict.FAIL: 0.0, Verdict.UNCERTAIN: 0.0}
    for r in nondet:
        weight[r.verdict] += r.confidence
    total = sum(weight.values())
    if total == 0:
        return Assessment(
            verdict=Verdict.UNCERTAIN, confidence=0.0, explanation="zero-confidence votes"
        )

    both_sides = weight[Verdict.PASS] > 0 and weight[Verdict.FAIL] > 0
    if weight[Verdict.PASS] == weight[Verdict.FAIL]:
        winner = Verdict.UNCERTAIN
    else:
        winner = Verdict.FAIL if weight[Verdict.FAIL] > weight[Verdict.PASS] else Verdict.PASS
    share = max(weight[Verdict.PASS], weight[Verdict.FAIL]) / total
    side = [r for r in nondet if r.verdict == winner]
    if winner == Verdict.UNCERTAIN or share < agreement_threshold:
        return Assessment(
            verdict=Verdict.UNCERTAIN,
            confidence=round(1 - share, 4) if winner != Verdict.UNCERTAIN else 0.0,
            agreement=round(share, 4),
            disagreement=both_sides,
            explanation=_summarise(nondet),
        )
    return Assessment(
        verdict=winner,
        confidence=round(share * mean(r.confidence for r in side), 4),
        agreement=round(share, 4),
        disagreement=both_sides,
        explanation=_summarise(side),
    )


def _summarise(results: list[EvaluationResult]) -> str:
    return "; ".join(
        f"{r.evaluator} [{r.verdict.value} {r.confidence:.2f}]: {r.explanation}" for r in results
    )
