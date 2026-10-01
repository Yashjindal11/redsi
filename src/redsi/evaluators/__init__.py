"""Evaluators judge target outputs; :func:`aggregate` combines their votes."""

from redsi.evaluators.aggregate import aggregate
from redsi.evaluators.base import (
    EvalContext,
    Evaluator,
    OutputEvaluator,
    build_evaluator,
    evaluators,
    register,
)
from redsi.evaluators.function import FunctionEvaluator
from redsi.evaluators.heuristics import AcknowledgesUncertainty, AsksClarification, Refuses
from redsi.evaluators.judge import LLMJudge
from redsi.evaluators.relational import ConsistentWithParent, SelfConsistency
from redsi.evaluators.rules import (
    Contains,
    ExactMatch,
    JSONSchema,
    Length,
    NonEmpty,
    NotContains,
    NumericAnswer,
    Regex,
    ToolCalled,
    ToolCallsBounded,
    ToolErrorsHandled,
    ToolNotCalled,
)
from redsi.evaluators.semantic import SemanticSimilarity, TokenOverlap, openai_embedder

__all__ = [
    "AcknowledgesUncertainty",
    "AsksClarification",
    "ConsistentWithParent",
    "Contains",
    "EvalContext",
    "Evaluator",
    "ExactMatch",
    "FunctionEvaluator",
    "JSONSchema",
    "LLMJudge",
    "Length",
    "NonEmpty",
    "NotContains",
    "NumericAnswer",
    "OutputEvaluator",
    "Refuses",
    "Regex",
    "SelfConsistency",
    "SemanticSimilarity",
    "TokenOverlap",
    "ToolCalled",
    "ToolCallsBounded",
    "ToolErrorsHandled",
    "ToolNotCalled",
    "aggregate",
    "build_evaluator",
    "evaluators",
    "openai_embedder",
    "register",
]
