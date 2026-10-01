"""Target adapter interface.

A *target* is the system under test. RedSI only needs one coroutine from it::

    class MyTarget(TargetAdapter):
        async def run(self, input: TargetInput) -> TargetOutput: ...

Adapters declare which parts of :class:`TargetInput` they actually use
(``capabilities``). Tests that need a capability the target does not have
(for example retrieved context) are *skipped and reported*, rather than
silently run with the context dropped.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from redsi.core.models import TargetInput, TargetOutput

ALL_CAPABILITIES: frozenset[str] = frozenset({"text", "system", "history", "context", "tools"})


class TargetRef(BaseModel):
    """How to rebuild a target later. Never contains secret values."""

    kind: str
    name: str
    params: dict[str, Any] = Field(default_factory=dict)
    reproducible: bool = True


class TargetAdapter(ABC):
    kind: ClassVar[str] = "custom"

    name: str = "target"
    capabilities: frozenset[str] = frozenset({"text"})
    timeout: float | None = 60.0

    @abstractmethod
    async def run(self, input: TargetInput) -> TargetOutput:
        """Execute the target once for ``input``."""

    def ref(self) -> TargetRef:
        cls = type(self)
        return TargetRef(
            kind=self.kind,
            name=self.name,
            params={"class": f"{cls.__module__}:{cls.__qualname__}"},
            reproducible=False,
        )

    def missing_capabilities(self, input: TargetInput) -> set[str]:
        return input.required_capabilities() - set(self.capabilities)

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        """Release resources (HTTP clients, processes)."""

    async def __aenter__(self) -> TargetAdapter:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


class TargetTimeoutError(Exception):
    pass


async def invoke(
    target: TargetAdapter, input: TargetInput, timeout: float | None = None
) -> TargetOutput:
    """Run ``target`` with a timeout and convert exceptions into error outputs.

    The returned output always has ``latency_ms`` set. Exceptions raised by the
    target are captured in ``output.error`` so one broken call never aborts a
    campaign.
    """
    limit = timeout if timeout is not None else target.timeout
    start = time.perf_counter()
    try:
        output = await asyncio.wait_for(target.run(input), timeout=limit)
        if not isinstance(output, TargetOutput):
            raise TypeError(f"{type(target).__name__}.run must return TargetOutput")
    except TimeoutError:
        output = TargetOutput(error=f"timeout after {limit}s")
    except Exception as exc:
        output = TargetOutput(error=f"{type(exc).__name__}: {exc}")
    if output.latency_ms is None:
        output.latency_ms = (time.perf_counter() - start) * 1000
    return output


def coerce_output(value: Any) -> TargetOutput:
    """Accept the common return shapes of user functions."""
    if isinstance(value, TargetOutput):
        return value
    if isinstance(value, str):
        return TargetOutput(text=value)
    if value is None:
        return TargetOutput(text="")
    if isinstance(value, dict):
        data = dict(value)
        if "text" not in data:
            for alias in ("answer", "output", "response", "content"):
                if isinstance(data.get(alias), str):
                    data["text"] = data.pop(alias)
                    break
        known = set(TargetOutput.model_fields)
        extra = {k: data.pop(k) for k in list(data) if k not in known}
        out = TargetOutput.model_validate(data)
        out.metadata.update(extra)
        return out
    return TargetOutput(text=str(value))
