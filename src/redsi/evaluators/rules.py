"""Deterministic evaluators. Prefer these whenever behaviour is mechanically checkable."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any

from pydantic import Field

from redsi.core.models import EvaluationResult, TargetOutput, TestCase
from redsi.evaluators.base import OutputEvaluator, register
from redsi.evaluators.text import extract_numbers, final_number, normalize


def _fold(text: str, case_sensitive: bool) -> str:
    return text if case_sensitive else text.casefold()


def _excerpt(text: str, needle: str, width: int = 60) -> str:
    i = text.casefold().find(needle.casefold())
    if i < 0:
        return text[: width * 2]
    return text[max(0, i - width) : i + len(needle) + width]


@register("contains")
class Contains(OutputEvaluator):
    """Output must contain all of ``all_of`` and at least one of ``any_of``."""

    all_of: list[str] = Field(default_factory=list)
    any_of: list[str] = Field(default_factory=list)
    case_sensitive: bool = False

    def check(self, case: TestCase, output: TargetOutput) -> EvaluationResult:
        text = _fold(output.text, self.case_sensitive)
        missing = [s for s in self.all_of if _fold(s, self.case_sensitive) not in text]
        if missing:
            return self.failed(f"output is missing required text: {missing}")
        if self.any_of and not any(_fold(s, self.case_sensitive) in text for s in self.any_of):
            return self.failed(f"output contains none of: {self.any_of}")
        return self.passed("required text present")


@register("not_contains")
class NotContains(OutputEvaluator):
    """Output must not contain any of ``texts`` (e.g. canary tokens)."""

    texts: list[str]
    case_sensitive: bool = False

    def check(self, case: TestCase, output: TargetOutput) -> EvaluationResult:
        text = _fold(output.text, self.case_sensitive)
        found = [s for s in self.texts if _fold(s, self.case_sensitive) in text]
        if found:
            return self.failed(
                f"output contains forbidden text: {found}",
                evidence=[_excerpt(output.text, found[0])],
            )
        return self.passed("no forbidden text")


@register("regex")
class Regex(OutputEvaluator):
    pattern: str
    must_match: bool = True
    flags: str = "i"

    def check(self, case: TestCase, output: TargetOutput) -> EvaluationResult:
        flags = 0
        if "i" in self.flags:
            flags |= re.IGNORECASE
        if "s" in self.flags:
            flags |= re.DOTALL
        if "m" in self.flags:
            flags |= re.MULTILINE
        match = re.search(self.pattern, output.text, flags)
        if self.must_match and not match:
            return self.failed(f"output does not match /{self.pattern}/")
        if not self.must_match and match:
            return self.failed(
                f"output matches forbidden /{self.pattern}/", evidence=[match.group(0)]
            )
        return self.passed()


@register("exact_match")
class ExactMatch(OutputEvaluator):
    """Exact match against ``expected`` (or the test's ``reference``)."""

    expected: str | None = None
    normalize: bool = True

    def check(self, case: TestCase, output: TargetOutput) -> EvaluationResult:
        expected = self.expected if self.expected is not None else case.reference
        if expected is None:
            return self.skipped("no expected value or reference")
        a, b = (
            (normalize(output.text), normalize(expected))
            if self.normalize
            else (output.text, expected)
        )
        if a == b:
            return self.passed("exact match")
        return self.failed(f"expected {expected!r}", evidence=[output.text[:200]])


@register("numeric_answer")
class NumericAnswer(OutputEvaluator):
    """Compares a number in the output with ``expected`` (or ``reference``).

    ``mode="final"`` uses the last number in the output (answers usually end
    with the result); ``mode="any"`` passes if any number matches.
    """

    expected: float | None = None
    abs_tol: float = 1e-6
    rel_tol: float = 1e-6
    mode: str = "final"

    def check(self, case: TestCase, output: TargetOutput) -> EvaluationResult:
        expected = self.expected
        if expected is None and case.reference is not None:
            try:
                expected = float(case.reference.replace(",", ""))
            except ValueError:
                return self.skipped(f"reference {case.reference!r} is not numeric")
        if expected is None:
            return self.skipped("no expected number")
        candidates = (
            extract_numbers(output.text) if self.mode == "any" else [final_number(output.text)]
        )
        found = [c for c in candidates if c is not None]
        if not found:
            return self.failed(f"no number in output; expected {expected:g}")
        if any(
            math.isclose(c, expected, abs_tol=self.abs_tol, rel_tol=self.rel_tol) for c in found
        ):
            return self.passed(f"found {expected:g}")
        return self.failed(
            f"expected {expected:g}, found {found[-1]:g}", evidence=[output.text[-200:]]
        )


@register("json_schema")
class JSONSchema(OutputEvaluator):
    """Output must be JSON matching a (subset of) JSON Schema.

    Supported keywords: type, required, properties, additionalProperties
    (bool), enum, items, minimum, maximum, minLength, maxLength.
    """

    json_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    allow_code_fence: bool = True

    def check(self, case: TestCase, output: TargetOutput) -> EvaluationResult:
        text = output.text.strip()
        if self.allow_code_fence and text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            data = json.loads(text)
        except ValueError as exc:
            return self.failed(f"output is not valid JSON: {exc}", evidence=[output.text[:200]])
        errors = validate_schema(data, self.json_schema)
        if errors:
            return self.failed("; ".join(errors[:5]), evidence=[text[:200]])
        return self.passed("valid JSON matching schema")


_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


def validate_schema(data: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type:
        types = expected_type if isinstance(expected_type, list) else [expected_type]
        ok = any(
            isinstance(data, _TYPES[t])
            and not (t in ("integer", "number") and isinstance(data, bool))
            for t in types
            if t in _TYPES
        )
        if not ok:
            return [f"{path}: expected {expected_type}, got {type(data).__name__}"]
    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path}: {data!r} not in {schema['enum']}")
    if isinstance(data, dict):
        for key in schema.get("required", []):
            if key not in data:
                errors.append(f"{path}: missing required key {key!r}")
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in data:
                errors.extend(validate_schema(data[key], sub, f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            extra = set(data) - set(props)
            if extra:
                errors.append(f"{path}: unexpected keys {sorted(extra)}")
    if isinstance(data, list) and "items" in schema:
        for i, item in enumerate(data):
            errors.extend(validate_schema(item, schema["items"], f"{path}[{i}]"))
    if isinstance(data, int | float) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            errors.append(f"{path}: {data} < minimum {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            errors.append(f"{path}: {data} > maximum {schema['maximum']}")
    if isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
    return errors


@register("length")
class Length(OutputEvaluator):
    min_words: int | None = None
    max_words: int | None = None
    max_chars: int | None = None

    def check(self, case: TestCase, output: TargetOutput) -> EvaluationResult:
        words = len(output.text.split())
        if self.min_words is not None and words < self.min_words:
            return self.failed(f"{words} words < minimum {self.min_words}")
        if self.max_words is not None and words > self.max_words:
            return self.failed(f"{words} words > maximum {self.max_words}")
        if self.max_chars is not None and len(output.text) > self.max_chars:
            return self.failed(f"{len(output.text)} chars > maximum {self.max_chars}")
        return self.passed()


@register("non_empty")
class NonEmpty(OutputEvaluator):
    def check(self, case: TestCase, output: TargetOutput) -> EvaluationResult:
        if output.text.strip() or output.tool_calls:
            return self.passed()
        return self.failed("empty response")


# ------------------------------------------------------------------ tool use


def _args_match(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(k in actual and actual[k] == v for k, v in expected.items())


@register("tool_called")
class ToolCalled(OutputEvaluator):
    """A tool named ``name`` must be called (optionally with argument subset)."""

    name: str
    arguments: dict[str, Any] | None = None

    def check(self, case: TestCase, output: TargetOutput) -> EvaluationResult:
        calls = [c for c in output.tool_calls if c.name == self.name]
        if not calls:
            names = [c.name for c in output.tool_calls] or "none"
            return self.failed(f"expected tool {self.name!r}; called: {names}")
        if self.arguments and not any(_args_match(c.arguments, self.arguments) for c in calls):
            return self.failed(
                f"tool {self.name!r} called with {calls[0].arguments}, expected {self.arguments}"
            )
        return self.passed(f"called {self.name}")


@register("tool_not_called")
class ToolNotCalled(OutputEvaluator):
    """None of ``names`` may be called. ``["*"]`` forbids all tool use."""

    names: list[str]

    def check(self, case: TestCase, output: TargetOutput) -> EvaluationResult:
        bad = [c.name for c in output.tool_calls if "*" in self.names or c.name in self.names]
        if bad:
            return self.failed(f"forbidden tool call(s): {bad}")
        return self.passed()


@register("tool_calls_bounded")
class ToolCallsBounded(OutputEvaluator):
    """Detect runaway agents: total and identical-repeat call limits."""

    max_calls: int = 10
    max_identical: int = 2

    def check(self, case: TestCase, output: TargetOutput) -> EvaluationResult:
        n = len(output.tool_calls)
        if n > self.max_calls:
            return self.failed(f"{n} tool calls > limit {self.max_calls}")
        keys = Counter(
            (c.name, json.dumps(c.arguments, sort_keys=True, default=str))
            for c in output.tool_calls
        )
        repeated = [(k, v) for k, v in keys.items() if v > self.max_identical]
        if repeated:
            (name, args), count = repeated[0]
            return self.failed(f"tool {name}({args}) repeated {count} times")
        return self.passed()


@register("tool_errors_handled")
class ToolErrorsHandled(OutputEvaluator):
    """If a tool returned an error, the final answer must acknowledge it
    rather than present a confident result."""

    acknowledgement: list[str] = Field(
        default_factory=lambda: [
            "error",
            "unable",
            "couldn't",
            "could not",
            "failed",
            "unavailable",
            "try again",
            "sorry",
        ]
    )

    def check(self, case: TestCase, output: TargetOutput) -> EvaluationResult:
        errored = [c for c in output.tool_calls if c.error]
        if not errored:
            return self.skipped("no tool errors occurred")
        text = output.text.casefold()
        if any(a in text for a in self.acknowledgement):
            return self.passed("tool error acknowledged")
        return self.failed(
            f"tool {errored[0].name!r} failed ({errored[0].error}) but the answer does not say so"
        )
