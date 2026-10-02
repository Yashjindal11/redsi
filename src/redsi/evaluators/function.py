"""Wrap a plain Python function as an evaluator.

The function may return ``bool``, a score in ``[0, 1]``, ``(bool, reason)``,
a dict with ``verdict``/``passed``, or an :class:`EvaluationResult`::

    def no_prices(input: str, output: str) -> bool:
        return "$" not in output

If the function is importable (module-level, not a lambda), its import path
is stored so findings stay reproducible.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from pydantic import PrivateAttr

from redsi.core.models import EvaluationResult, TargetOutput, TestCase, Verdict
from redsi.evaluators.base import EvalContext, Evaluator, register

# Callables wrapped in this process, so specs can find them again even when
# they are not importable (closures, lambdas). Not reproducible across processes.
_LOCAL: dict[str, Callable[..., Any]] = {}


@register("function")
class FunctionEvaluator(Evaluator):
    path: str | None = None
    name: str | None = None
    local: str | None = None
    threshold: float = 0.5
    is_deterministic: bool = True

    _fn: Callable[..., Any] | None = PrivateAttr(default=None)

    @classmethod
    def wrap(
        cls, fn: Callable[..., Any], *, threshold: float = 0.5, deterministic: bool = True
    ) -> FunctionEvaluator:
        from redsi.targets.function import _import_path_of

        path = _import_path_of(fn)
        local = None
        if path is None:
            # Stable across runs (keeps test ids stable); suffixed only on collision.
            base = f"{getattr(fn, '__module__', '')}:{getattr(fn, '__qualname__', '')}:{getattr(fn, '__name__', '')}"
            local, i = base, 1
            while local in _LOCAL and _LOCAL[local] is not fn:
                i += 1
                local = f"{base}#{i}"
            _LOCAL[local] = fn
        else:
            _LOCAL[path] = fn
        ev = cls(
            path=path,
            name=getattr(fn, "__name__", "function"),
            local=local,
            threshold=threshold,
            is_deterministic=deterministic,
        )
        ev._fn = fn
        return ev

    def _resolve(self) -> Callable[..., Any]:
        if self._fn is None:
            key = self.local or self.path
            if key and key in _LOCAL:
                self._fn = _LOCAL[key]
            elif self.path:
                from redsi.targets.function import resolve_import

                self._fn = resolve_import(self.path)
            else:
                raise RuntimeError(
                    f"function evaluator {self.name!r} is not importable and was defined in "
                    "another process; define it at module level to make it reproducible"
                )
        return self._fn

    def label(self) -> str:
        return f"function:{self.name or self.path or 'anonymous'}"

    async def evaluate(
        self, case: TestCase, outputs: list[TargetOutput], ctx: EvalContext
    ) -> EvaluationResult:
        fn = self._resolve()
        label = self.label()
        usable = [o for o in outputs if o.ok]
        if not usable:
            return self.skipped("no successful output")
        params = inspect.signature(fn).parameters
        wants_objects = any(
            p.annotation in (TestCase, TargetOutput, "TestCase", "TargetOutput")
            for p in params.values()
        )
        for output in usable:
            args = (case, output) if wants_objects else (case.input.prompt, output.text)
            value = fn(*args)
            if inspect.isawaitable(value):
                value = await value
            result = self._coerce(value, label)
            if result.verdict == Verdict.FAIL:
                return result
        return result

    def _coerce(self, value: Any, label: str) -> EvaluationResult:
        det = self.is_deterministic
        if isinstance(value, EvaluationResult):
            return value
        if isinstance(value, tuple) and len(value) == 2:
            ok, reason = value
            return self._from_bool(bool(ok), str(reason), det)
        if isinstance(value, bool):
            return self._from_bool(value, f"{label} returned {value}", det)
        if isinstance(value, int | float):
            ok = float(value) >= self.threshold
            r = self._from_bool(
                ok, f"{label} score {float(value):.3f} (threshold {self.threshold})", det
            )
            r.score = float(value)
            return r
        if isinstance(value, dict):
            if "verdict" in value:
                return EvaluationResult(evaluator=label, deterministic=det, **value)
            return self._from_bool(bool(value.get("passed")), str(value.get("reason", "")), det)
        raise TypeError(f"{label} returned unsupported type {type(value).__name__}")

    def _from_bool(self, ok: bool, reason: str, det: bool) -> EvaluationResult:
        if ok:
            return self.passed(reason, deterministic=det)
        return self.failed(reason, deterministic=det)
