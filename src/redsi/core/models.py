"""Foundational schemas shared by every RedSI subsystem.

These models are the public, serialisable vocabulary of RedSI: what goes into
a target, what comes out, what a test is, how an evaluator judged it, and
what a finding is. They have no dependencies on targets, providers or the
campaign engine.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from redsi.core.severity import Severity


def utcnow() -> datetime:
    return datetime.now(UTC)


def stable_hash(payload: Any, length: int = 12) -> str:
    """Deterministic short hash of a JSON-serialisable payload."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:length]


# --------------------------------------------------------------------------- I/O


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None


class Document(BaseModel):
    content: str
    id: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolSpec(BaseModel):
    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any | None = None
    error: str | None = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: Usage) -> Usage:
        cost: float | None
        if self.cost_usd is None and other.cost_usd is None:
            cost = None
        else:
            cost = (self.cost_usd or 0.0) + (other.cost_usd or 0.0)
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cost_usd=cost,
        )


Capability = Literal["text", "system", "history", "context", "tools"]


class TargetInput(BaseModel):
    """Everything RedSI sends to a target for one call."""

    prompt: str
    system: str | None = None
    history: list[Message] = Field(default_factory=list)
    context: list[Document] = Field(default_factory=list)
    tools: list[ToolSpec] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def required_capabilities(self) -> set[str]:
        caps = {"text"}
        if self.system:
            caps.add("system")
        if self.history:
            caps.add("history")
        if self.context:
            caps.add("context")
        if self.tools:
            caps.add("tools")
        return caps

    def render_text(self) -> str:
        """Flatten system, context and history into one prompt string.

        Used for targets that only accept a single string, when the user
        explicitly opts in to flattening.
        """
        parts: list[str] = []
        if self.system:
            parts.append(f"[Instructions]\n{self.system}")
        if self.context:
            docs = "\n\n".join(
                f"[Document {d.id or i + 1}]\n{d.content}" for i, d in enumerate(self.context)
            )
            parts.append(f"[Context]\n{docs}")
        for m in self.history:
            parts.append(f"[{m.role}]\n{m.content}")
        parts.append(self.prompt if not parts else f"[user]\n{self.prompt}")
        return "\n\n".join(parts)


class TargetOutput(BaseModel):
    """Everything observed from one target call."""

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    retrieved: list[Document] = Field(default_factory=list)
    usage: Usage | None = None
    latency_ms: float | None = None
    error: str | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None


# ------------------------------------------------------------------- test cases


class EvaluatorSpec(BaseModel):
    """Serialisable reference to an evaluator: registry ``type`` plus params."""

    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class Origin(BaseModel):
    """Where a test came from. ``strategies`` is the mutation chain."""

    generator: str
    strategies: list[str] = Field(default_factory=list)
    parent_id: str | None = None
    seed: int | None = None
    round: int = 0


class Relation(BaseModel):
    """A metamorphic relation between this test's output and another test's.

    ``consistent`` means the answers should agree (paraphrase, noise).
    """

    kind: Literal["consistent"] = "consistent"
    case_id: str


class TestCase(BaseModel):
    """A single executable, evaluable test."""

    __test__: ClassVar[bool] = False  # keep pytest from collecting this class

    model_config = ConfigDict(arbitrary_types_allowed=False)

    id: str = ""
    input: TargetInput
    category: str
    expected_behavior: str | None = None
    reference: str | None = None
    # None means "use the taxonomy default for this category".
    severity: Severity | None = None
    tags: list[str] = Field(default_factory=list)
    evaluators: list[EvaluatorSpec] = Field(default_factory=list)
    origin: Origin | None = None
    relation: Relation | None = None
    requirements: list[str] = Field(default_factory=list)
    samples: int = Field(default=1, ge=1, le=50)
    suite: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input", mode="before")
    @classmethod
    def _coerce_input(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"prompt": value}
        return value

    @field_validator("evaluators", mode="before")
    @classmethod
    def _coerce_evaluators(cls, value: Any) -> Any:
        if not isinstance(value, list):
            value = [value]
        out = []
        for item in value:
            to_spec = getattr(item, "to_spec", None)
            out.append(to_spec() if callable(to_spec) else item)
        return out

    @model_validator(mode="after")
    def _assign_id(self) -> TestCase:
        if not self.id:
            self.id = "T-" + stable_hash(self.identity())
        return self

    def identity(self) -> dict[str, Any]:
        """Fields that define *what* is tested; used for stable ids."""
        return {
            "input": self.input.model_dump(mode="json", exclude={"metadata"}),
            "category": self.category,
            "reference": self.reference,
            "evaluators": [e.model_dump(mode="json") for e in self.evaluators],
            "relation": self.relation.model_dump(mode="json") if self.relation else None,
            "samples": self.samples,
        }


# ------------------------------------------------------------------- evaluation


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"
    ERROR = "error"
    SKIP = "skip"


class EvaluationResult(BaseModel):
    evaluator: str
    verdict: Verdict
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    deterministic: bool = True
    score: float | None = None
    explanation: str = ""
    evidence: list[str] = Field(default_factory=list)
    usage: Usage | None = None
    error: str | None = None


class Assessment(BaseModel):
    """Aggregate judgement over all evaluator results for one test."""

    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    agreement: float | None = None
    disagreement: bool = False
    deterministic_failure: bool = False
    explanation: str = ""


class CaseRecord(BaseModel):
    """A test plus everything observed when it was executed and evaluated."""

    case: TestCase
    outputs: list[TargetOutput] = Field(default_factory=list)
    results: list[EvaluationResult] = Field(default_factory=list)
    assessment: Assessment
    skipped_reason: str | None = None
    started_at: datetime = Field(default_factory=utcnow)
    duration_ms: float = 0.0

    @property
    def verdict(self) -> Verdict:
        return self.assessment.verdict


# ---------------------------------------------------------------------- findings


class FindingStatus(StrEnum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    UNCERTAIN = "uncertain"
    FALSE_POSITIVE = "false_positive"


class RootCause(StrEnum):
    MODEL_LIMITATION = "model_limitation"
    PROMPT_WEAKNESS = "prompt_weakness"
    RETRIEVAL_FAILURE = "retrieval_failure"
    TOOL_FAILURE = "tool_failure"
    CONTEXT_FAILURE = "context_failure"
    INSTRUCTION_CONFLICT = "instruction_conflict"
    WORKFLOW_ISSUE = "workflow_issue"
    EVALUATION_ERROR = "evaluation_error"
    DATA_ISSUE = "data_issue"
    UNKNOWN = "unknown"


class Hypothesis(BaseModel):
    """An *inferred* root cause. Never presented as observed fact."""

    cause: RootCause
    likelihood: Literal["low", "medium", "high"] = "low"
    evidence: list[str] = Field(default_factory=list)
    source: str = "heuristic"


class Reproducibility(BaseModel):
    attempts: int = 0
    failures: int = 0
    checked_at: datetime | None = None
    flaky: bool = False

    @property
    def rate(self) -> float | None:
        return None if self.attempts == 0 else self.failures / self.attempts


class Finding(BaseModel):
    id: str
    fingerprint: str
    run_id: str
    case_id: str
    category: str
    severity: Severity
    status: FindingStatus
    confidence: float = Field(ge=0.0, le=1.0)
    title: str
    input: TargetInput
    output: TargetOutput
    expected: str | None = None
    explanation: str = ""
    evidence: list[str] = Field(default_factory=list)
    results: list[EvaluationResult] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    reproducibility: Reproducibility | None = None
    origin: Origin | None = None
    requirements: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def evaluators(self) -> list[str]:
        return [r.evaluator for r in self.results]
