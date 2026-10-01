"""Similarity to a reference answer.

``TokenOverlap`` is transparent and dependency-free but only lexical.
``SemanticSimilarity`` uses an embedding function supplied through the
evaluation context (``EvalContext.embedder``); without one it is skipped
rather than silently falling back to something weaker.
"""

from __future__ import annotations

import math
import os
from typing import Any

import httpx
from pydantic import Field

from redsi.core.models import EvaluationResult, TargetOutput, TestCase
from redsi.evaluators.base import Embedder, EvalContext, Evaluator, OutputEvaluator, register
from redsi.evaluators.text import token_f1


@register("token_overlap")
class TokenOverlap(OutputEvaluator):
    """Token F1 against ``reference``. Lexical only; use for short factual answers."""

    reference: str | None = None
    threshold: float = Field(default=0.5, ge=0, le=1)
    deterministic = True

    def check(self, case: TestCase, output: TargetOutput) -> EvaluationResult:
        ref = self.reference or case.reference
        if not ref:
            return self.skipped("no reference")
        score = token_f1(output.text, ref)
        if score >= self.threshold:
            return self.passed(f"token F1 {score:.2f}", score=score)
        return self.failed(f"token F1 {score:.2f} < {self.threshold}", score=score)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


@register("semantic_similarity")
class SemanticSimilarity(Evaluator):
    """Embedding cosine similarity to ``reference``.

    Thresholds are model-specific; calibrate them on your own data before
    trusting the verdicts. Scores between the thresholds are ``uncertain``.
    """

    deterministic = False
    reference: str | None = None
    pass_threshold: float = Field(default=0.85, ge=-1, le=1)
    fail_threshold: float = Field(default=0.6, ge=-1, le=1)

    async def evaluate(
        self, case: TestCase, outputs: list[TargetOutput], ctx: EvalContext
    ) -> EvaluationResult:
        ref = self.reference or case.reference
        usable = [o for o in outputs if o.ok]
        if not ref or not usable:
            return self.skipped("no reference or output")
        if ctx.embedder is None:
            return self.skipped("no embedder configured")
        vectors = await ctx.embedder([ref, usable[0].text])
        score = cosine(vectors[0], vectors[1])
        if score >= self.pass_threshold:
            return self.passed(f"cosine {score:.3f}", score=score, confidence=0.7)
        if score <= self.fail_threshold:
            return self.failed(f"cosine {score:.3f}", score=score, confidence=0.7)
        return self.uncertain(f"cosine {score:.3f} between thresholds", score=score, confidence=0.3)


def openai_embedder(
    model: str = "text-embedding-3-small",
    *,
    base_url: str = "https://api.openai.com/v1",
    api_key_env: str | None = "OPENAI_API_KEY",
    timeout: float = 60.0,
) -> Embedder:
    """Embedding function for any OpenAI-compatible ``/embeddings`` endpoint."""

    async def embed(texts: list[str]) -> list[list[float]]:
        headers: dict[str, Any] = {}
        key = os.environ.get(api_key_env) if api_key_env else None
        if key:
            headers["authorization"] = f"Bearer {key}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/embeddings",
                json={"model": model, "input": texts},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
        return [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]

    return embed
