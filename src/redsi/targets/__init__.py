"""Target adapters and the :class:`Target` factory."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from redsi.core.registry import Registry
from redsi.targets.base import (
    ALL_CAPABILITIES,
    TargetAdapter,
    TargetRef,
    coerce_output,
    invoke,
)
from redsi.targets.function import FunctionTarget, IsolatedFunctionTarget, from_import
from redsi.targets.http import HTTPTarget
from redsi.targets.model import ModelTarget, build_model_target

TargetBuilder = Callable[[TargetRef], TargetAdapter]

#: Maps ``TargetRef.kind`` to a function that rebuilds the target.
target_kinds: Registry[TargetBuilder] = Registry("target kind", "redsi.targets")


def _build_import(ref: TargetRef) -> TargetAdapter:
    p = ref.params
    return from_import(
        p["path"],
        isolate=bool(p.get("isolate", False)),
        flatten=bool(p.get("flatten", False)),
        timeout=p.get("timeout", 60.0),
    )


def _build_http(ref: TargetRef) -> TargetAdapter:
    p = dict(ref.params)
    return HTTPTarget(p.pop("url"), name=ref.name, **p)


target_kinds.register("import", _build_import)
target_kinds.register("http", _build_http)
for _kind in ("model", "openai", "anthropic", "ollama", "gemini", "huggingface"):
    target_kinds.register(_kind, build_model_target)


class Target:
    """Factory for target adapters. ``Target.from_*`` return a TargetAdapter."""

    @staticmethod
    def from_function(
        fn: Callable[..., Any],
        *,
        name: str | None = None,
        flatten: bool = False,
        timeout: float | None = 60.0,
    ) -> TargetAdapter:
        return FunctionTarget(fn, name=name, flatten=flatten, timeout=timeout)

    @staticmethod
    def from_import(
        path: str, *, isolate: bool = False, flatten: bool = False, timeout: float | None = 60.0
    ) -> TargetAdapter:
        return from_import(path, isolate=isolate, flatten=flatten, timeout=timeout)

    @staticmethod
    def from_http(url: str, **kwargs: Any) -> TargetAdapter:
        return HTTPTarget(url, **kwargs)

    @staticmethod
    def from_openai(
        model: str,
        *,
        base_url: str | None = None,
        api_key_env: str | None = "OPENAI_API_KEY",
        system: str | None = None,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
    ) -> TargetAdapter:
        """A chat model behind any OpenAI-compatible endpoint."""
        provider: dict[str, Any] = {"type": "openai", "model": model, "api_key_env": api_key_env}
        if base_url:
            provider["base_url"] = base_url
        return ModelTarget(provider, system=system, temperature=temperature, max_tokens=max_tokens)

    @staticmethod
    def from_model(provider: Any, **kwargs: Any) -> TargetAdapter:
        """A chat model from a provider instance, config dict or ``"type:model"``."""
        return ModelTarget(provider, **kwargs)

    @staticmethod
    def from_ref(ref: TargetRef | dict[str, Any]) -> TargetAdapter:
        ref = TargetRef.model_validate(ref)
        if not ref.reproducible:
            raise ValueError(
                f"target {ref.name!r} cannot be rebuilt from its reference; "
                "pass the target explicitly"
            )
        return target_kinds.get(ref.kind)(ref)

    @staticmethod
    def load(spec: str, **kwargs: Any) -> TargetAdapter:
        """Parse a CLI-style target string.

        * ``https://host/path`` - HTTP endpoint
        * ``openai:<model>``, ``ollama:<model>``, ... - chat model
        * ``path/to/file.py[:attr]`` or ``pkg.module:attr`` - Python callable
        """
        if spec.startswith(("http://", "https://")):
            return HTTPTarget(spec, **kwargs)
        scheme, sep, rest = spec.partition(":")
        if sep and scheme in target_kinds and scheme not in ("import", "http", "model"):
            return target_kinds.get(scheme)(
                TargetRef(kind=scheme, name=rest, params={"model": rest, **kwargs})
            )
        return from_import(spec, **kwargs)


__all__ = [
    "ALL_CAPABILITIES",
    "FunctionTarget",
    "HTTPTarget",
    "IsolatedFunctionTarget",
    "ModelTarget",
    "Target",
    "TargetAdapter",
    "TargetRef",
    "coerce_output",
    "invoke",
    "target_kinds",
]
