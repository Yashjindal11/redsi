"""Model provider interface.

Providers are the models *RedSI itself* uses (test generation, judging,
root-cause analysis). They are deliberately separate from targets: the system
under test and the judge should be swappable independently.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from redsi.core.models import Message, ToolCall, ToolSpec, Usage, stable_hash


class ChatRequest(BaseModel):
    messages: list[Message]
    temperature: float | None = 0.0
    max_tokens: int | None = None
    json_mode: bool = False
    seed: int | None = None
    tools: list[ToolSpec] = Field(default_factory=list)
    stop: list[str] = Field(default_factory=list)

    @classmethod
    def simple(cls, prompt: str, system: str | None = None, **kwargs: Any) -> ChatRequest:
        messages = [Message(role="system", content=system)] if system else []
        messages.append(Message(role="user", content=prompt))
        return cls(messages=messages, **kwargs)


class ChatResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    model: str = ""
    latency_ms: float = 0.0
    finish_reason: str | None = None
    cached: bool = False


class Pricing(BaseModel):
    """USD per million tokens. RedSI ships no price table: prices change, so
    users supply them. Without pricing, cost is reported as unknown."""

    input_per_mtok: float
    output_per_mtok: float

    def cost(self, usage: Usage) -> float:
        return (
            usage.prompt_tokens * self.input_per_mtok
            + usage.completion_tokens * self.output_per_mtok
        ) / 1_000_000


class ProviderError(RuntimeError):
    pass


class ModelProvider(ABC):
    name: str = "provider"
    model: str = ""
    pricing: Pricing | None = None

    @abstractmethod
    async def complete(self, request: ChatRequest) -> ChatResponse: ...

    def describe(self) -> dict[str, Any]:
        """Serialisable description for run artifacts (no secrets)."""
        return {"provider": self.name, "model": self.model}

    def _price(self, usage: Usage) -> Usage:
        if self.pricing is not None:
            usage.cost_usd = self.pricing.cost(usage)
        return usage

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        """Release network resources."""


Responder = Callable[[ChatRequest], "str | ChatResponse | Awaitable[str | ChatResponse]"]


class ScriptedProvider(ModelProvider):
    """Deterministic provider for tests, examples and offline runs.

    ``responses`` is either a list (cycled) or a function of the request.
    """

    name = "scripted"

    def __init__(self, responses: Sequence[str] | Responder, model: str = "scripted") -> None:
        self.model = model
        self._responses = responses
        self._i = 0
        self.requests: list[ChatRequest] = []

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if callable(self._responses):
            value = self._responses(request)
            if inspect.isawaitable(value):
                value = await value
        else:
            items = list(self._responses)
            value = items[self._i % len(items)]
            self._i += 1
        if isinstance(value, ChatResponse):
            return value
        prompt_tokens = sum(len(m.content.split()) for m in request.messages)
        return ChatResponse(
            text=str(value),
            model=self.model,
            usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=len(str(value).split())),
        )


class CachedProvider(ModelProvider):
    """Cache deterministic requests (temperature 0) in memory and optionally on disk."""

    def __init__(self, inner: ModelProvider, directory: str | Path | None = None) -> None:
        self.inner = inner
        self.name = inner.name
        self.model = inner.model
        self.pricing = inner.pricing
        self.directory = Path(directory) if directory else None
        self._memory: dict[str, ChatResponse] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.hits = 0

    def describe(self) -> dict[str, Any]:
        return self.inner.describe()

    async def complete(self, request: ChatRequest) -> ChatResponse:
        if request.temperature not in (0, 0.0, None):
            return await self.inner.complete(request)
        key = stable_hash(
            {"model": self.inner.describe(), "req": request.model_dump(mode="json")}, 24
        )
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self._memory.get(key) or self._read(key)
            if hit is not None:
                self.hits += 1
                # Cached responses cost nothing now; keep token counts for reference.
                return hit.model_copy(
                    update={
                        "cached": True,
                        "usage": Usage(**{**hit.usage.model_dump(), "cost_usd": 0.0}),
                    }
                )
            response = await self.inner.complete(request)
            self._memory[key] = response
            self._write(key, response)
            return response

    def _read(self, key: str) -> ChatResponse | None:
        if self.directory is None:
            return None
        path = self.directory / f"{key}.json"
        if not path.is_file():
            return None
        return ChatResponse.model_validate_json(path.read_text("utf-8"))

    def _write(self, key: str, response: ChatResponse) -> None:
        if self.directory is None:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{key}.json").write_text(response.model_dump_json(), "utf-8")

    async def aclose(self) -> None:
        await self.inner.aclose()


async def with_retries(
    fn: Callable[[], Awaitable[Any]],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    retry_on: tuple[type[BaseException], ...] = (ProviderError,),
) -> Any:
    for attempt in range(attempts):
        try:
            return await fn()
        except retry_on:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(base_delay * (2**attempt))
    raise AssertionError("unreachable")


def parse_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from model output (tolerates code fences)."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model output")
    data = json.loads(stripped[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model output is not a JSON object")
    return data


def elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000
