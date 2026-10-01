"""OpenAI-compatible chat completions provider.

Covers OpenAI and the many servers that implement the same API (Ollama,
vLLM, LM Studio, llama.cpp server, Hugging Face router, Gemini's OpenAI
endpoint, ...). Only the env-var *name* of the API key is stored.
"""

from __future__ import annotations

import json
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

OPENAI_BASE_URL = "https://api.openai.com/v1"


class OpenAICompatibleProvider(ModelProvider):
    name = "openai"

    def __init__(
        self,
        model: str,
        *,
        base_url: str = OPENAI_BASE_URL,
        api_key_env: str | None = "OPENAI_API_KEY",
        pricing: Pricing | None = None,
        timeout: float = 120.0,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        extra_body: dict[str, Any] | None = None,
        name: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.pricing = pricing
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.extra_body = dict(extra_body or {})
        if name:
            self.name = name
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
        }

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        key = os.environ.get(self.api_key_env) if self.api_key_env else None
        if key:
            headers["authorization"] = f"Bearer {key}"
        elif self.api_key_env and self.base_url == OPENAI_BASE_URL:
            raise ProviderError(f"environment variable {self.api_key_env} is not set")
        return headers

    def build_payload(self, request: ChatRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": m.role, "content": m.content, **({"name": m.name} if m.name else {})}
                for m in request.messages
            ],
            **self.extra_body,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.seed is not None:
            payload["seed"] = request.seed
        if request.stop:
            payload["stop"] = request.stop
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in request.tools
            ]
        return payload

    async def complete(self, request: ChatRequest) -> ChatResponse:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout, transport=self._transport)
        payload = self.build_payload(request)
        headers = self._headers()
        start = time.perf_counter()

        async def call() -> httpx.Response:
            assert self._client is not None
            try:
                resp = await self._client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
            except httpx.TransportError as exc:
                raise ProviderError(f"transport error: {exc}") from exc
            if resp.status_code == 429 or resp.status_code >= 500:
                raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            return resp

        resp: httpx.Response = await with_retries(
            call, attempts=self.max_retries, base_delay=self.retry_base_delay
        )
        if resp.status_code >= 400:
            raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return self.parse_response(resp.json(), elapsed_ms(start))

    def parse_response(self, data: dict[str, Any], latency_ms: float) -> ChatResponse:
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"unexpected response shape: {str(data)[:300]}") from exc
        calls = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except ValueError:
                args = {"_raw": raw_args}
            calls.append(ToolCall(name=fn.get("name", ""), arguments=args))
        u = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(u.get("prompt_tokens") or 0),
            completion_tokens=int(u.get("completion_tokens") or 0),
        )
        return ChatResponse(
            text=message.get("content") or "",
            tool_calls=calls,
            usage=self._price(usage),
            model=str(data.get("model") or self.model),
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason"),
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
