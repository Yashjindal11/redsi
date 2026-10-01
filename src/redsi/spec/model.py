"""Specification-driven testing.

A specification states what a system must and must not do::

    system:
      name: customer_support
      description: Answers questions about airline baggage policies.
    behavior:
      must:
        - provide accurate policy information
        - id: ask-missing
          text: request missing information when necessary
          checks: [{type: asks_clarification}]
      must_not:
        - text: expose internal instructions
          severity: critical
          checks: [{type: not_contains, params: {texts: ["INTERNAL-ONLY"]}}]
    seeds:
      - What is the checked bag allowance on economy?
    facts:
      - Economy fares include one 23 kg checked bag.

Requirements compile into evaluators (explicit ``checks`` plus an LLM-judge
rubric) and into tests (seeds, explicit ``probes`` and, with a generator
model, generated probes). Coverage is reported per requirement.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from redsi.core.models import Document, EvaluatorSpec
from redsi.core.severity import Severity

_CATEGORY_HINTS: tuple[tuple[str, str], ...] = (
    (r"citation|cite|source|reference", "factuality.fabricated_citation"),
    (r"invent|fabricat|hallucinat|make up|made[- ]up", "factuality.hallucination"),
    (r"uncertain|don't know|do not know|unsure", "factuality.hallucination"),
    (r"missing information|clarif|ask for", "robustness.missing_information"),
    (r"ambigu", "robustness.ambiguity"),
    (
        r"instruction|system prompt|internal|confidential|secret|leak|reveal|expose",
        "security.data_leakage",
    ),
    (r"inject", "security.prompt_injection"),
    (r"tool|book|purchase|send|delete|refund", "agent.tool_misuse"),
    (r"json|format|schema", "reliability.format"),
    (r"accurate|correct|fact", "factuality.unsupported_claim"),
    (r"consistent", "reliability.inconsistency"),
)


def infer_category(text: str) -> str:
    for pattern, category in _CATEGORY_HINTS:
        if re.search(pattern, text, re.IGNORECASE):
            return category
    return "reliability.instruction_following"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "requirement"


class Requirement(BaseModel):
    id: str = ""
    kind: Literal["must", "must_not"] = "must"
    text: str
    severity: Severity | None = None
    category: str | None = None
    checks: list[EvaluatorSpec] = Field(default_factory=list)
    probes: list[str] = Field(default_factory=list)

    @property
    def statement(self) -> str:
        verb = "must" if self.kind == "must" else "must not"
        return f"The system {verb} {self.text.rstrip('.')}."

    @property
    def resolved_category(self) -> str:
        return self.category or infer_category(self.text)


class Seed(BaseModel):
    input: str
    reference: str | None = None
    expected_behavior: str | None = None
    checks: list[EvaluatorSpec] = Field(default_factory=list)


class SystemInfo(BaseModel):
    name: str
    description: str = ""
    target: str | None = None


class Behavior(BaseModel):
    must: list[Requirement] = Field(default_factory=list)
    must_not: list[Requirement] = Field(default_factory=list)

    @field_validator("must", "must_not", mode="before")
    @classmethod
    def _coerce(cls, value: Any) -> Any:
        return [{"text": v} if isinstance(v, str) else v for v in value or []]


class Specification(BaseModel):
    version: int = 1
    system: SystemInfo
    behavior: Behavior = Field(default_factory=Behavior)
    seeds: list[Seed] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    system_prompt: str | None = None
    context: list[Document] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)

    @field_validator("seeds", mode="before")
    @classmethod
    def _coerce_seeds(cls, value: Any) -> Any:
        return [{"input": v} if isinstance(v, str) else v for v in value or []]

    @field_validator("context", mode="before")
    @classmethod
    def _coerce_context(cls, value: Any) -> Any:
        return [{"content": v} if isinstance(v, str) else v for v in value or []]

    @model_validator(mode="after")
    def _assign_ids(self) -> Specification:
        seen: set[str] = set()
        groups: tuple[tuple[Literal["must", "must_not"], list[Requirement]], ...] = (
            ("must", self.behavior.must),
            ("must_not", self.behavior.must_not),
        )
        for kind, reqs in groups:
            for r in reqs:
                r.kind = kind
                if not r.id:
                    prefix = "must" if kind == "must" else "must-not"
                    r.id = f"{prefix}:{_slug(r.text)}"
                if r.id in seen:
                    raise ValueError(f"duplicate requirement id {r.id!r}")
                seen.add(r.id)
        return self

    @property
    def requirements(self) -> list[Requirement]:
        return [*self.behavior.must, *self.behavior.must_not]

    def requirement(self, req_id: str) -> Requirement:
        for r in self.requirements:
            if r.id == req_id:
                return r
        raise KeyError(req_id)

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.system.name,
            "description": self.system.description,
            "requirements": [
                {"id": r.id, "kind": r.kind, "text": r.text, "checks": [c.type for c in r.checks]}
                for r in self.requirements
            ],
        }

    @classmethod
    def load(cls, path: str | Path) -> Specification:
        data = yaml.safe_load(Path(path).read_text("utf-8")) or {}
        return cls.model_validate(data)
