"""Structured events.

Every meaningful step of a campaign emits an :class:`Event`. Sinks receive
redacted events; a failing sink is logged and never breaks a run. New
integrations (OpenTelemetry, LangSmith, ...) are just additional sinks.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from redsi.core.models import utcnow
from redsi.observability.redaction import Redactor, default_redactor

log = logging.getLogger("redsi")


class EventType(StrEnum):
    CAMPAIGN_STARTED = "campaign.started"
    CAMPAIGN_FINISHED = "campaign.finished"
    GENERATION_FINISHED = "generation.finished"
    CASE_STARTED = "case.started"
    CASE_FINISHED = "case.finished"
    CASE_SKIPPED = "case.skipped"
    TARGET_CALL = "target.call"
    MODEL_CALL = "model.call"
    EVALUATION = "evaluation"
    TOOL_CALL = "tool.call"
    RETRY = "retry"
    BUDGET_EXHAUSTED = "budget.exhausted"
    EARLY_STOP = "early_stop"
    FINDING = "finding"
    ERROR = "error"


class Event(BaseModel):
    type: str
    ts: datetime = Field(default_factory=utcnow)
    run_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class EventSink(Protocol):
    def handle(self, event: Event) -> None: ...


class MemorySink:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def handle(self, event: Event) -> None:
        self.events.append(event)

    def of_type(self, type_: str) -> list[Event]:
        return [e for e in self.events if e.type == type_]


class JsonlSink:
    """Append events to a JSON-lines file (used for live dashboards)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def handle(self, event: Event) -> None:
        line = event.model_dump_json()
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


class CallbackSink:
    def __init__(self, fn: Callable[[Event], None]) -> None:
        self.fn = fn

    def handle(self, event: Event) -> None:
        self.fn(event)


class LoggingSink:
    def __init__(self, level: int = logging.DEBUG) -> None:
        self.level = level

    def handle(self, event: Event) -> None:
        log.log(self.level, "%s %s", event.type, json.dumps(event.data, default=str))


class EventBus:
    def __init__(
        self,
        sinks: list[EventSink] | None = None,
        *,
        run_id: str | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        self.sinks: list[EventSink] = list(sinks or [])
        self.run_id = run_id
        self.redactor = redactor or default_redactor()

    def subscribe(self, sink: EventSink) -> None:
        self.sinks.append(sink)

    def emit(self, type_: str, **data: Any) -> Event:
        event = Event(type=str(type_), run_id=self.run_id, data=self.redactor.obj(data))
        for sink in self.sinks:
            try:
                sink.handle(event)
            except Exception:  # observability must never break a run
                log.warning("event sink %r failed", sink, exc_info=True)
        return event


NULL_BUS = EventBus()
