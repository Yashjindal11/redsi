"""Small plugin registry with optional entry-point discovery.

Third-party packages can register components by exposing an entry point in
one of the ``redsi.*`` groups, e.g. in their ``pyproject.toml``::

    [project.entry-points."redsi.evaluators"]
    my_check = "my_pkg.checks:MyCheck"
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from importlib.metadata import entry_points
from typing import Generic, TypeVar

T = TypeVar("T")
log = logging.getLogger("redsi")


def _same_origin(a: object, b: object) -> bool:
    """True when ``b`` is the same definition as ``a`` from a re-imported module."""
    qa, qb = getattr(a, "__qualname__", None), getattr(b, "__qualname__", None)
    ma, mb = getattr(a, "__module__", None), getattr(b, "__module__", None)
    return qa is not None and qa == qb and ma == mb


class Registry(Generic[T]):
    def __init__(self, kind: str, entry_point_group: str | None = None) -> None:
        self.kind = kind
        self.group = entry_point_group
        self._items: dict[str, T] = {}
        self._loaded_entry_points = False

    def register(self, name: str, item: T, *, replace: bool = False) -> T:
        existing = self._items.get(name)
        if existing is not None and not replace and not _same_origin(existing, item):
            raise ValueError(f"{self.kind} {name!r} is already registered")
        self._items[name] = item
        return item

    def decorator(self, name: str) -> Callable[[T], T]:
        def wrap(item: T) -> T:
            return self.register(name, item)

        return wrap

    def get(self, name: str) -> T:
        self._load_entry_points()
        try:
            return self._items[name]
        except KeyError:
            known = ", ".join(sorted(self._items)) or "none"
            raise KeyError(f"unknown {self.kind} {name!r} (known: {known})") from None

    def names(self) -> list[str]:
        self._load_entry_points()
        return sorted(self._items)

    def __contains__(self, name: object) -> bool:
        self._load_entry_points()
        return name in self._items

    def __iter__(self) -> Iterator[str]:
        return iter(self.names())

    def _load_entry_points(self) -> None:
        if self._loaded_entry_points or self.group is None:
            return
        self._loaded_entry_points = True
        for ep in entry_points(group=self.group):
            if ep.name in self._items:
                continue
            try:
                self._items[ep.name] = ep.load()
            except Exception:
                log.warning("failed to load %s plugin %r", self.kind, ep.name, exc_info=True)
