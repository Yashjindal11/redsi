"""Campaign configuration and run modes."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from redsi.core.severity import SeverityPolicy


class Mode(StrEnum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"
    CUSTOM = "custom"


class CampaignConfig(BaseModel):
    """Everything that controls *how* a campaign runs (not *what* it tests)."""

    mode: Mode = Mode.STANDARD
    suites: list[str] = Field(default_factory=list)
    categories: list[str] = Field(
        default_factory=list, description="glob filters, e.g. 'security.*'"
    )
    tags: list[str] = Field(default_factory=list)
    concurrency: int = Field(default=8, ge=1, le=256)
    timeout: float | None = Field(default=60.0, gt=0)
    retries: int = Field(default=1, ge=0, le=10)
    max_cases: int | None = Field(default=None, ge=1)
    max_target_calls: int | None = Field(default=None, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)
    max_failures: int | None = Field(default=None, ge=1, description="stop early after N failures")
    samples: int | None = Field(default=None, ge=1, le=50, description="override samples per test")
    seed: int = 0
    agreement_threshold: float = Field(default=0.67, ge=0.5, le=1.0)
    likely_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    errors_as_findings: bool = True
    severity: SeverityPolicy = Field(default_factory=SeverityPolicy)
    fuzz: dict[str, Any] | None = None

    def resolved(self) -> CampaignConfig:
        """Apply mode presets to fields the user left unset."""
        preset = MODE_PRESETS.get(self.mode, {})
        updates = {k: v for k, v in preset.items() if getattr(self, k) is None}
        return self.model_copy(update=updates)


MODE_PRESETS: dict[Mode, dict[str, Any]] = {
    Mode.QUICK: {"max_cases": 60, "fuzz": None},
    Mode.STANDARD: {"max_cases": 400, "fuzz": {"per_seed": 2, "rounds": 1}},
    Mode.DEEP: {"max_cases": 3000, "fuzz": {"per_seed": 4, "rounds": 3, "depth": 2}},
    Mode.CUSTOM: {},
}
