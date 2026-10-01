"""Anthropic Messages API provider."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from redsi.core.models import ToolCall, Usage
from redsi.providers.base import (
    ChatRequest,
    ChatResponse,
    ModelProvider,
    Pricing,
    ProviderError,
    elapsed_ms,
    with_retries,
)

ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(ModelProvider):
    name = "anthropic"

    def __init__(
        self,
        model: str,
        *,
        api_key_env: str = "ANTHROPIC_API_KEY",
        base_url: str = ANTHROPIC_BASE_URL,
        pricing: Pricing | None = None,
        timeout: float = 120.0,
        max_retries: int = 3,
        default_max_tokens: int = 1024,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.api_key_env = api_key_env
        self.base_url = base_url.rstrip("/")
        self.pricing = pricing
        self.timeout = timeout
        self.max_retries = max_retries
        self.default_max_tokens = default_max_tokens
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "api_key_env": self.api_key_env}

    def build_payload(self, request: ChatRequest) -> dict[str, Any]:
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        messages = [
            {"role": "assistant" if m.role == "assistant" else "user", "content": m.content}
            for m in request.messages
            if m.role != "system"
        ]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_tokens or self.default_max_tokens,
        }
        if system:
            payload["system"] = system
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.stop:
            payload["stop_sequences"] = request.stop
        if request.tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in request.tools
            ]
        return payload

    async def complete(self, request: ChatRequest) -> ChatResponse:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ProviderError(f"environment variable {self.api_key_env} is not set")
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout, transport=self._transport)
        headers = {
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        payload = self.build_payload(request)
        start = time.perf_counter()

        async def call() -> httpx.Response:
            assert self._client is not None
            try:
                resp = await self._client.post(
                    f"{self.base_url}/messages", json=payload, headers=headers
                )
            except httpx.TransportError as exc:
                raise ProviderError(f"transport error: {exc}") from exc
            if resp.status_code in (429, 529) or resp.status_code >= 500:
                raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            return resp

        resp: httpx.Response = await with_retries(call, attempts=self.max_retries)
        if resp.status_code >= 400:
            raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        texts, calls = [], []
        for block in data.get("content", []):
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                calls.append(
                    ToolCall(name=block.get("name", ""), arguments=block.get("input") or {})
                )
        u = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(u.get("input_tokens") or 0),
            completion_tokens=int(u.get("output_tokens") or 0),
        )
        return ChatResponse(
            text="".join(texts),
            tool_calls=calls,
            usage=self._price(usage),
            model=str(data.get("model") or self.model),
            latency_ms=elapsed_ms(start),
            finish_reason=data.get("stop_reason"),
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
