"""Secret redaction applied to events, artifacts and reports.

Redaction is best-effort defence in depth. The primary control is that
RedSI references secrets by environment-variable *name* and never stores
their values.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from typing import Any

REDACTED = "[REDACTED]"

_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}",
        r"AKIA[0-9A-Z]{16}",
        r"gh[pousr]_[A-Za-z0-9]{20,}",
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"xox[abprs]-[A-Za-z0-9\-]{10,}",
        r"AIza[0-9A-Za-z\-_]{35}",
        r"hf_[A-Za-z0-9]{20,}",
        r"(?i)bearer\s+[A-Za-z0-9\-._~+/]{16,}=*",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    )
)
_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|secret|password|passwd)\b(\s*[:=]\s*[\"']?)([^\s\"',}]{8,})"
)
_SECRET_ENV_NAME = re.compile(r"(?i)(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)")


class Redactor:
    def __init__(self, extra_values: Iterable[str] = (), *, include_env: bool = True) -> None:
        values = {v for v in extra_values if v and len(v) >= 8}
        if include_env:
            values |= {
                v for k, v in os.environ.items() if _SECRET_ENV_NAME.search(k) and v and len(v) >= 8
            }
        # Longest first so overlapping secrets are fully replaced.
        self._values = sorted(values, key=len, reverse=True)

    def text(self, value: str) -> str:
        for secret in self._values:
            if secret in value:
                value = value.replace(secret, REDACTED)
        for pattern in _PATTERNS:
            value = pattern.sub(REDACTED, value)
        return _ASSIGNMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", value)

    def obj(self, value: Any) -> Any:
        """Recursively redact strings inside JSON-like structures."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {k: self.obj(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self.obj(v) for v in value]
        return value


_default: Redactor | None = None


def default_redactor() -> Redactor:
    global _default
    if _default is None:
        _default = Redactor()
    return _default


def redact(value: Any) -> Any:
    return default_redactor().obj(value)
