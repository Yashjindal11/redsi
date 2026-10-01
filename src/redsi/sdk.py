"""Public Python SDK.

from redsi import RedSI, Target

redsi = RedSI(Target.from_function(my_agent))
run = await redsi.run(tests=[...])
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from redsi.campaign import CampaignConfig, CampaignRunner, RunArtifact, new_run_id
from redsi.core.models import TestCase
from redsi.core.severity import SeverityPolicy
from redsi.evaluators.base import Embedder
from redsi.observability.events import EventBus, EventSink, JsonlSink
from redsi.providers import ModelProvider, ModelRoles
from redsi.store import RunStore
from redsi.targets import Target, TargetAdapter


class RedSI:
    def __init__(
        self,
        target: TargetAdapter | Callable[..., Any] | str,
        *,
        judges: Sequence[ModelProvider] = (),
        generator: ModelProvider | None = None,
        analyst: ModelProvider | None = None,
        embedder: Embedder | None = None,
        store: RunStore | str | Path | None = ".redsi",
        sinks: Sequence[EventSink] = (),
        severity: SeverityPolicy | None = None,
    ) -> None:
        if isinstance(target, TargetAdapter):
            self.target = target
        elif isinstance(target, str):
            self.target = Target.load(target)
        else:
            self.target = Target.from_function(target)
        self.models = ModelRoles(generator=generator, judges=list(judges), analyst=analyst)
        self.embedder = embedder
        self.store = store if isinstance(store, RunStore) or store is None else RunStore(store)
        self.sinks = list(sinks)
        self.severity = severity

    def _bus(self, run_id: str) -> EventBus:
        sinks = list(self.sinks)
        if self.store is not None:
            sinks.append(JsonlSink(self.store.events_path(run_id)))
        return EventBus(sinks, run_id=run_id)

    async def run(
        self,
        *,
        tests: Iterable[TestCase] = (),
        config: CampaignConfig | None = None,
        name: str | None = None,
        save: bool = True,
        **overrides: Any,
    ) -> RunArtifact:
        """Run a campaign over ``tests``. ``overrides`` set CampaignConfig fields."""
        cfg = (config or CampaignConfig()).model_copy(update=overrides)
        if self.severity is not None:
            cfg.severity = self.severity
        cases = list(tests)
        run_id = new_run_id()
        runner = CampaignRunner(
            self.target,
            cfg,
            models=self.models,
            embedder=self.embedder,
            bus=self._bus(run_id),
            run_id=run_id,
        )
        artifact = await runner.run(cases, name=name)
        if save and self.store is not None:
            self.store.save(artifact)
        return artifact

    def run_sync(self, **kwargs: Any) -> RunArtifact:
        return asyncio.run(self.run(**kwargs))

    async def aclose(self) -> None:
        await self.target.aclose()
        await self.models.aclose()
