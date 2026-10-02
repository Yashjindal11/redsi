"""Python function targets.

Supported function shapes (sync or async)::

    def agent(prompt: str) -> str
    def rag(prompt: str, context: list[Document]) -> str | dict | TargetOutput
    def full(input: TargetInput) -> TargetOutput

Keyword parameters named ``system``, ``history``, ``context`` or ``tools``
receive the corresponding part of the input and declare that capability.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import multiprocessing as mp
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from redsi.core.models import TargetInput, TargetOutput
from redsi.targets.base import ALL_CAPABILITIES, TargetAdapter, TargetRef, coerce_output

_KWARG_CAPS = ("system", "history", "context", "tools")
_DEFAULT_ATTRS = ("redsi_target", "target", "agent", "chat", "run", "predict", "main")


class FunctionTarget(TargetAdapter):
    kind = "function"

    def __init__(
        self,
        fn: Callable[..., Any],
        *,
        name: str | None = None,
        flatten: bool = False,
        timeout: float | None = 60.0,
        import_path: str | None = None,
    ) -> None:
        if not callable(fn):
            raise TypeError("fn must be callable")
        self.fn = fn
        self.name = name or str(getattr(fn, "__name__", "function"))
        self.timeout = timeout
        self.flatten = flatten
        self.import_path = import_path or _import_path_of(fn)
        self._is_async = inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(
            getattr(fn, "__call__", None)  # noqa: B004 - callable objects with async __call__
        )
        self._mode, self._kwargs = _inspect_signature(fn)
        if flatten or self._mode == "input":
            self.capabilities = ALL_CAPABILITIES
        else:
            self.capabilities = frozenset({"text", *self._kwargs})

    async def run(self, input: TargetInput) -> TargetOutput:
        args, kwargs = self._build_call(input)
        if self._is_async:
            result = await self.fn(*args, **kwargs)
        else:
            # Threads cannot be killed: use isolate=True for hard timeouts.
            result = await asyncio.to_thread(self.fn, *args, **kwargs)
        return coerce_output(result)

    def _build_call(self, input: TargetInput) -> tuple[list[Any], dict[str, Any]]:
        if self._mode == "input":
            return [input], {}
        prompt = input.render_text() if self.flatten else input.prompt
        kwargs = {k: getattr(input, k) for k in self._kwargs}
        return [prompt], kwargs

    def ref(self) -> TargetRef:
        if self.import_path is None:
            return TargetRef(kind="function", name=self.name, reproducible=False)
        return TargetRef(
            kind="import",
            name=self.name,
            params={"path": self.import_path, "flatten": self.flatten, "timeout": self.timeout},
        )


def _inspect_signature(fn: Callable[..., Any]) -> tuple[str, tuple[str, ...]]:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return "prompt", ()
    params = [p for p in sig.parameters.values() if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
    if params:
        first = params[0]
        ann = first.annotation
        if ann is TargetInput or ann == "TargetInput" or first.name in ("input", "target_input"):
            return "input", ()
    kwargs = tuple(p.name for p in params[1:] if p.name in _KWARG_CAPS)
    return "prompt", kwargs


def _import_path_of(fn: Callable[..., Any]) -> str | None:
    module = getattr(fn, "__module__", None)
    qualname = getattr(fn, "__qualname__", None)
    if not module or not qualname or "<" in qualname or module.startswith("<"):
        return None
    if module == "__main__":
        main_file = getattr(sys.modules.get("__main__"), "__file__", None)
        return f"{Path(main_file).resolve()}:{qualname}" if main_file else None
    return f"{module}:{qualname}"


def resolve_import(path: str) -> Any:
    """Resolve ``"pkg.module:attr"`` or ``"path/to/file.py[:attr]"``."""
    module_part, _, attr = path.partition(":")
    if module_part.endswith(".py") or "/" in module_part or "\\" in module_part:
        file = Path(module_part).expanduser().resolve()
        if not file.is_file():
            raise FileNotFoundError(f"target file not found: {file}")
        mod_name = f"redsi_user_{file.stem}"
        # Always load fresh: the file may have changed since the last load.
        spec = importlib.util.spec_from_file_location(mod_name, file)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot import {file}")
        module = importlib.util.module_from_spec(spec)
        # Let the user's file import its siblings.
        if str(file.parent) not in sys.path:
            sys.path.insert(0, str(file.parent))
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
    else:
        if str(Path.cwd()) not in sys.path:
            sys.path.insert(0, str(Path.cwd()))
        module = importlib.import_module(module_part)

    if attr:
        obj: Any = module
        for part in attr.split("."):
            obj = getattr(obj, part)
        return obj
    found = [a for a in _DEFAULT_ATTRS if hasattr(module, a)]
    if not found:
        raise AttributeError(
            f"{path}: no target found; name one explicitly ('{path}:my_fn') "
            f"or define one of: {', '.join(_DEFAULT_ATTRS)}"
        )
    return getattr(module, found[0])


def from_import(
    path: str, *, isolate: bool = False, flatten: bool = False, timeout: float | None = 60.0
) -> TargetAdapter:
    obj = resolve_import(path)
    if isinstance(obj, TargetAdapter):
        return obj
    if isinstance(obj, type) and issubclass(obj, TargetAdapter):
        return obj()
    if not callable(obj):
        raise TypeError(f"{path} is neither a callable nor a TargetAdapter")
    if isolate:
        return IsolatedFunctionTarget(path, flatten=flatten, timeout=timeout, probe=obj)
    target = FunctionTarget(obj, flatten=flatten, timeout=timeout)
    target.import_path = _normalise_path(path, obj)
    return target


def _normalise_path(path: str, obj: Any) -> str:
    module_part, _, attr = path.partition(":")
    name = attr or getattr(obj, "__name__", "")
    if module_part.endswith(".py") or "/" in module_part:
        return f"{Path(module_part).expanduser().resolve()}:{name}"
    return f"{module_part}:{name}"


# ----------------------------------------------------------------- isolation


def _isolated_worker(path: str, flatten: bool, payload: str, queue: Any) -> None:
    try:
        target = from_import(path, flatten=flatten, timeout=None)
        result = asyncio.run(target.run(TargetInput.model_validate_json(payload)))
        queue.put(("ok", result.model_dump_json()))
    except BaseException as exc:
        queue.put(("error", f"{type(exc).__name__}: {exc}"))


class IsolatedFunctionTarget(TargetAdapter):
    """Run each call in a fresh process that is killed on timeout.

    Slower than in-process execution (one interpreter start per call) but the
    target cannot hang the campaign or mutate RedSI's process state.
    """

    kind = "import"

    def __init__(
        self,
        path: str,
        *,
        flatten: bool = False,
        timeout: float | None = 60.0,
        probe: Callable[..., Any] | None = None,
    ) -> None:
        self.path = _normalise_path(path, probe) if probe is not None else path
        self.name = self.path.rsplit(":", 1)[-1] or "isolated"
        self.flatten = flatten
        self.call_timeout = timeout
        # The outer timeout must exceed the kill timeout so the process is reaped.
        self.timeout = None if timeout is None else timeout + 10
        probe_target = FunctionTarget(probe or resolve_import(self.path), flatten=flatten)
        self.capabilities = probe_target.capabilities
        self._ctx = mp.get_context("spawn")

    async def run(self, input: TargetInput) -> TargetOutput:
        return await asyncio.to_thread(self._run_blocking, input.model_dump_json())

    def _run_blocking(self, payload: str) -> TargetOutput:
        queue = self._ctx.Queue()
        proc = self._ctx.Process(
            target=_isolated_worker, args=(self.path, self.flatten, payload, queue), daemon=True
        )
        proc.start()
        try:
            status, data = queue.get(timeout=self.call_timeout)
        except Exception:
            return TargetOutput(error=f"timeout after {self.call_timeout}s (process killed)")
        finally:
            if proc.is_alive():
                proc.kill()
            proc.join(timeout=5)
        if status == "ok":
            return TargetOutput.model_validate_json(data)
        return TargetOutput(error=data)

    def ref(self) -> TargetRef:
        return TargetRef(
            kind="import",
            name=self.name,
            params={
                "path": self.path,
                "flatten": self.flatten,
                "timeout": self.call_timeout,
                "isolate": True,
            },
        )
