"""Model providers and per-task model roles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from redsi.core.registry import Registry
from redsi.providers.anthropic import AnthropicProvider
from redsi.providers.base import (
    CachedProvider,
    ChatRequest,
    ChatResponse,
    ModelProvider,
    Pricing,
    ProviderError,
    ScriptedProvider,
    parse_json_object,
)
from redsi.providers.openai_compat import OpenAICompatibleProvider

ProviderFactory = Callable[..., ModelProvider]
providers: Registry[ProviderFactory] = Registry("provider", "redsi.providers")


def _openai(**kw: Any) -> ModelProvider:
    return OpenAICompatibleProvider(**kw)


def _preset(name: str, base_url: str, api_key_env: str | None) -> ProviderFactory:
    def build(**kw: Any) -> ModelProvider:
        kw.setdefault("base_url", base_url)
        kw.setdefault("api_key_env", api_key_env)
        return OpenAICompatibleProvider(name=name, **kw)

    return build


providers.register("openai", _openai)
providers.register("openai_compatible", _openai)
providers.register("anthropic", lambda **kw: AnthropicProvider(**kw))
# OpenAI-compatible presets. Verify the endpoint with your provider's docs.
providers.register("ollama", _preset("ollama", "http://localhost:11434/v1", None))
providers.register(
    "gemini",
    _preset("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
)
providers.register(
    "huggingface", _preset("huggingface", "https://router.huggingface.co/v1", "HF_TOKEN")
)


def provider_from_config(config: dict[str, Any] | str) -> ModelProvider:
    """Build a provider from ``{"type": "openai", "model": "...", ...}`` or
    the shorthand ``"openai:gpt-4o-mini"``."""
    if isinstance(config, str):
        kind, _, model = config.partition(":")
        config = {"type": kind, "model": model}
    cfg = dict(config)
    kind = cfg.pop("type", "openai")
    if "pricing" in cfg and isinstance(cfg["pricing"], dict):
        cfg["pricing"] = Pricing(**cfg["pricing"])
    return providers.get(kind)(**cfg)


@dataclass
class ModelRoles:
    """Which model performs which RedSI task. Any role may be unset.

    Using different models for generation and judging reduces the chance
    that one model's blind spots both create and grade the same tests.
    """

    generator: ModelProvider | None = None
    judges: list[ModelProvider] = field(default_factory=list)
    analyst: ModelProvider | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "generator": self.generator.describe() if self.generator else None,
            "judges": [j.describe() for j in self.judges],
            "analyst": self.analyst.describe() if self.analyst else None,
        }

    async def aclose(self) -> None:
        seen: set[int] = set()
        for p in [self.generator, self.analyst, *self.judges]:
            if p is not None and id(p) not in seen:
                seen.add(id(p))
                await p.aclose()


__all__ = [
    "AnthropicProvider",
    "CachedProvider",
    "ChatRequest",
    "ChatResponse",
    "ModelProvider",
    "ModelRoles",
    "OpenAICompatibleProvider",
    "Pricing",
    "ProviderError",
    "ScriptedProvider",
    "parse_json_object",
    "provider_from_config",
    "providers",
]
