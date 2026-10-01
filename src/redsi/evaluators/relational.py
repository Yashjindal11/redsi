"""Relational (metamorphic) evaluators: compare outputs with each other.

These need no ground truth, which is what makes them useful for fuzzing:
a paraphrased question should get a consistent answer whether or not RedSI
knows the right answer.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from pydantic import Field

from redsi.core.models import EvaluationResult, TargetOutput, TestCase
from redsi.evaluators.base import EvalContext, Evaluator, register
from redsi.evaluators.text import final_number, jaccard


def compare_answers(
    a: str, b: str, *, pass_similarity: float, fail_similarity: float
) -> tuple[str, float, str]:
    """Return (verdict, confidence, explanation) for two answers.

    Numbers are compared first (strong signal). Otherwise lexical overlap is
    used, which is weak: middling similarity is reported as uncertain.
    """
    na, nb = final_number(a), final_number(b)
    if na is not None and nb is not None:
        if math.isclose(na, nb, rel_tol=1e-6, abs_tol=1e-9):
            return "pass", 0.8, f"same final number ({na:g})"
        return "fail", 0.8, f"different final numbers ({na:g} vs {nb:g})"
    sim = jaccard(a, b)
    if sim >= pass_similarity:
        return "pass", 0.6, f"lexical similarity {sim:.2f}"
    if sim <= fail_similarity:
        return "fail", 0.5, f"lexical similarity {sim:.2f}"
    return "uncertain", 0.3, f"lexical similarity {sim:.2f} is inconclusive"


class _Comparator(Evaluator):
    deterministic = False
    pass_similarity: float = Field(default=0.5, ge=0, le=1)
    fail_similarity: float = Field(default=0.15, ge=0, le=1)

    def _verdict(self, verdict: str, conf: float, why: str, **kw: Any) -> EvaluationResult:
        if verdict == "pass":
            return self.passed(why, confidence=conf, **kw)
        if verdict == "fail":
            return self.failed(why, confidence=conf, **kw)
        return self.uncertain(why, confidence=conf, **kw)


@register("self_consistency")
class SelfConsistency(_Comparator):
    """All samples of the same test should agree (requires ``samples > 1``)."""

    async def evaluate(
        self, case: TestCase, outputs: list[TargetOutput], ctx: EvalContext
    ) -> EvaluationResult:
        texts = [o.text for o in outputs if o.ok]
        if len(texts) < 2:
            return self.skipped("needs at least two successful samples")
        worst: tuple[str, float, str] | None = None
        order = {"fail": 0, "uncertain": 1, "pass": 2}
        for a, b in itertools.combinations(texts, 2):
            v = compare_answers(
                a, b, pass_similarity=self.pass_similarity, fail_similarity=self.fail_similarity
            )
            if worst is None or order[v[0]] < order[worst[0]]:
                worst = v
        assert worst is not None
        verdict, conf, why = worst
        return self._verdict(
            verdict,
            conf,
            f"across {len(texts)} samples: {why}",
            evidence=[t[:160] for t in texts[:3]],
        )


@register("consistent_with_parent")
class ConsistentWithParent(_Comparator):
    """Output should agree with the output of the test named in ``case.relation``."""

    async def evaluate(
        self, case: TestCase, outputs: list[TargetOutput], ctx: EvalContext
    ) -> EvaluationResult:
        if case.relation is None:
            return self.skipped("test has no relation")
        parent = [o for o in ctx.outputs_by_case.get(case.relation.case_id, []) if o.ok]
        mine = [o for o in outputs if o.ok]
        if not parent or not mine:
            return self.skipped("parent or child output unavailable")
        verdict, conf, why = compare_answers(
            parent[0].text,
            mine[0].text,
            pass_similarity=self.pass_similarity,
            fail_similarity=self.fail_similarity,
        )
        return self._verdict(
            verdict,
            conf,
            f"vs original ({case.relation.case_id}): {why}",
            evidence=[f"original: {parent[0].text[:160]}", f"variant: {mine[0].text[:160]}"],
        )
