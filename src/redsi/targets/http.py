"""HTTP endpoint targets.

The request body is a JSON template. String values that are exactly a
placeholder are replaced by the raw value (so ``"{{context}}"`` becomes a
list); placeholders inside longer strings are replaced by text.

Placeholders: ``{{prompt}}``, ``{{system}}``, ``{{history}}``,
``{{context}}``, ``{{tools}}``, ``{{input}}`` (the whole TargetInput).

Header values may reference environment variables as ``${NAME}``. The
template (not the resolved value) is what gets stored in run artifacts.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from redsi.core.models import TargetInput, TargetOutput
from redsi.targets.base import TargetAdapter, TargetRef, coerce_output

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_ENV = re.compile(r"\$\{(\w+)\}")
_CAP_FOR_PLACEHOLDER = {
    "prompt": {"text"},
    "system": {"system"},
    "history": {"history"},
    "context": {"context"},
    "tools": {"tools"},
    "input": {"text", "system", "history", "context", "tools"},
}


class HTTPTarget(TargetAdapter):
    kind = "http"

    def __init__(
        self,
        url: str,
        *,
        method: str = "POST",
        body: Any = None,
        headers: dict[str, str] | None = None,
        response_path: str | None = None,
        name: str | None = None,
        timeout: float | None = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not url.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        self.url = url
        self.method = method.upper()
        self.body = body if body is not None else {"prompt": "{{prompt}}"}
        self.headers = dict(headers or {})
        self.response_path = response_path
        self.name = name or url
        self.timeout = timeout
        used = set(_PLACEHOLDER.findall(json.dumps(self.body)))
        caps: set[str] = set()
        for placeholder in used:
            caps |= _CAP_FOR_PLACEHOLDER.get(placeholder, set())
        self.capabilities = frozenset(caps | {"text"})
        self._client: httpx.AsyncClient | None = None
        self._transport = transport

    async def run(self, input: TargetInput) -> TargetOutput:
        if self._client is None:
            # Never follow redirects: the target is exactly the configured URL.
            self._client = httpx.AsyncClient(
                follow_redirects=False, timeout=self.timeout, transport=self._transport
            )
        values = _placeholder_values(input)
        payload = _render(self.body, values)
        kwargs: dict[str, Any] = {"headers": _resolve_env(self.headers)}
        if self.method in ("GET", "DELETE"):
            kwargs["params"] = payload if isinstance(payload, dict) else {"q": payload}
        else:
            kwargs["json"] = payload
        response = await self._client.request(self.method, self.url, **kwargs)
        if response.status_code >= 400:
            return TargetOutput(
                error=f"HTTP {response.status_code}: {response.text[:500]}",
                metadata={"status_code": response.status_code},
            )
        try:
            data: Any = response.json()
        except ValueError:
            return TargetOutput(text=response.text, metadata={"status_code": response.status_code})
        if self.response_path:
            data = extract_path(data, self.response_path)
        out = coerce_output(data)
        out.metadata.setdefault("status_code", response.status_code)
        return out

    def ref(self) -> TargetRef:
        return TargetRef(
            kind="http",
            name=self.name,
            params={
                "url": self.url,
                "method": self.method,
                "body": self.body,
                "headers": self.headers,  # templates like ${API_KEY}, not values
                "response_path": self.response_path,
                "timeout": self.timeout,
            },
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _placeholder_values(input: TargetInput) -> dict[str, Any]:
    return {
        "prompt": input.prompt,
        "system": input.system,
        "history": [m.model_dump() for m in input.history],
        "context": [d.model_dump() for d in input.context],
        "tools": [t.model_dump() for t in input.tools],
        "input": input.model_dump(mode="json"),
    }


def _render(template: Any, values: dict[str, Any]) -> Any:
    if isinstance(template, str):
        whole = _PLACEHOLDER.fullmatch(template)
        if whole and whole.group(1) in values:
            return values[whole.group(1)]

        def repl(m: re.Match[str]) -> str:
            v = values.get(m.group(1), m.group(0))
            return v if isinstance(v, str) else json.dumps(v)

        return _PLACEHOLDER.sub(repl, template)
    if isinstance(template, dict):
        return {k: _render(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [_render(v, values) for v in template]
    return template


def _resolve_env(headers: dict[str, str]) -> dict[str, str]:
    def repl(m: re.Match[str]) -> str:
        value = os.environ.get(m.group(1))
        if value is None:
            raise KeyError(f"environment variable {m.group(1)} is not set")
        return value

    return {k: _ENV.sub(repl, v) for k, v in headers.items()}


def extract_path(data: Any, path: str) -> Any:
    """Follow a dotted path like ``choices.0.message.content``."""
    for part in path.split("."):
        if isinstance(data, list):
            data = data[int(part)]
        elif isinstance(data, dict):
            data = data[part]
        else:
            raise KeyError(f"cannot follow {path!r} at {part!r}")
    return data
