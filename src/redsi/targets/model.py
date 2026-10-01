"""Targets backed by a chat model provider (OpenAI-compatible, Anthropic, ...).

This tests a *bare model* (plus an optional system prompt). To test an
application built on a model, wrap the application instead.
"""

from __future__ import annotations

from typing import Any

from redsi.core.models import Message, TargetInput, TargetOutput
from redsi.providers import ChatRequest, ModelProvider, provider_from_config
from redsi.targets.base import ALL_CAPABILITIES, TargetAdapter, TargetRef


class ModelTarget(TargetAdapter):
    kind = "model"
    capabilities = ALL_CAPABILITIES

    def __init__(
        self,
        provider: ModelProvider | dict[str, Any] | str,
        *,
        system: str | None = None,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        name: str | None = None,
        timeout: float | None = 120.0,
    ) -> None:
        self.provider_config: dict[str, Any] | None
        if isinstance(provider, ModelProvider):
            self.provider = provider
            self.provider_config = None
        else:
            self.provider_config = (
                {"type": provider.partition(":")[0], "model": provider.partition(":")[2]}
                if isinstance(provider, str)
                else dict(provider)
            )
            self.provider = provider_from_config(self.provider_config)
        self.system = system
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.name = name or f"{self.provider.name}:{self.provider.model}"
        self.timeout = timeout

    def build_messages(self, input: TargetInput) -> list[Message]:
        system_parts = [p for p in (self.system, input.system) if p]
        if input.context:
            docs = "\n\n".join(
                f"[Document {d.id or i + 1}]\n{d.content}" for i, d in enumerate(input.context)
            )
            system_parts.append(f"Context documents:\n{docs}")
        messages = (
            [Message(role="system", content="\n\n".join(system_parts))] if system_parts else []
        )
        messages.extend(input.history)
        messages.append(Message(role="user", content=input.prompt))
        return messages

    async def run(self, input: TargetInput) -> TargetOutput:
        response = await self.provider.complete(
            ChatRequest(
                messages=self.build_messages(input),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                tools=input.tools,
                seed=input.metadata.get("seed"),
            )
        )
        return TargetOutput(
            text=response.text,
            tool_calls=response.tool_calls,
            usage=response.usage,
            metadata={"model": response.model, "finish_reason": response.finish_reason},
        )

    def ref(self) -> TargetRef:
        return TargetRef(
            kind="model",
            name=self.name,
            params={
                "provider": self.provider_config or self.provider.describe(),
                "system": self.system,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            },
            reproducible=self.provider_config is not None,
        )

    async def aclose(self) -> None:
        await self.provider.aclose()


def build_model_target(ref: TargetRef) -> TargetAdapter:
    p = dict(ref.params)
    if ref.kind != "model":
        # Shorthand kinds like "openai" / "ollama": params carry provider kwargs.
        provider = {"type": ref.kind, "model": p.pop("model")}
        for key in ("base_url", "api_key_env", "pricing"):
            if key in p:
                provider[key] = p.pop(key)
        return ModelTarget(provider, name=ref.name if ref.name != provider["model"] else None, **p)
    return ModelTarget(p.pop("provider"), name=ref.name, **p)
