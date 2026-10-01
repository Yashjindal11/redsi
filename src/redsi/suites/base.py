"""Test suites: named, versioned collections of test cases.

Built-in suites are organised by failure domain and contain no external
datasets. Every built-in test has a mechanically checkable expectation
(exact numbers, canary tokens, schemas, tool calls) or is explicitly marked
as needing a heuristic/judge, in which case its findings can never be
``confirmed`` without a deterministic check.

Custom suites::

    from redsi.suites import suite

    @suite("billing", "Billing assistant regressions")
    def billing() -> list[TestCase]:
        return [TestCase(...)]

or a YAML/JSONL file of test cases (see ``load_tests``).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from redsi.core.models import TestCase
from redsi.core.registry import Registry

Builder = Callable[[], list[TestCase]]


@dataclass(frozen=True)
class Suite:
    name: str
    description: str
    builder: Builder
    version: str = "1"

    def cases(self) -> list[TestCase]:
        out = []
        for c in self.builder():
            tags = c.tags if self.name in c.tags else [self.name, *c.tags]
            out.append(c.model_copy(update={"suite": c.suite or self.name, "tags": tags}))
        return out


suites: Registry[Suite] = Registry("suite", "redsi.suites")


def suite(name: str, description: str, version: str = "1") -> Callable[[Builder], Builder]:
    def wrap(fn: Builder) -> Builder:
        suites.register(name, Suite(name, description, fn, version))
        return fn

    return wrap


def load_tests(path: str | Path) -> list[TestCase]:
    """Load test cases from ``.yaml``/``.yml``/``.json`` (a list) or ``.jsonl``."""
    path = Path(path)
    text = path.read_text("utf-8")
    items: list[Any]
    if path.suffix == ".jsonl":
        items = [json.loads(line) for line in text.splitlines() if line.strip()]
    elif path.suffix == ".json":
        items = json.loads(text)
    else:
        items = yaml.safe_load(text) or []
    if isinstance(items, dict):
        items = items.get("tests", [])
    return [TestCase.model_validate(item) for item in items]


def resolve_suites(names: Iterable[str]) -> list[TestCase]:
    """Resolve suite names (``all``, a registered name, or a test file path)."""
    _ensure_builtins()
    out: list[TestCase] = []
    for name in names:
        if name == "all":
            for n in suites.names():
                out.extend(suites.get(n).cases())
        elif name in suites:
            out.extend(suites.get(name).cases())
        elif Path(name).suffix in (".yaml", ".yml", ".json", ".jsonl") and Path(name).is_file():
            out.extend(load_tests(name))
        else:
            raise KeyError(f"unknown suite {name!r} (known: {', '.join(suites.names())})")
    return out


def _ensure_builtins() -> None:
    import redsi.suites.builtin  # noqa: F401 - registers built-in suites on import
