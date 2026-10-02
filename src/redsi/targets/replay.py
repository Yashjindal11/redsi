"""Replay pre-recorded outputs, for evaluating logs without calling a live system."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from redsi.core.models import TargetInput, TargetOutput, TestCase, stable_hash
from redsi.targets.base import ALL_CAPABILITIES, TargetAdapter, TargetRef, coerce_output


def _key(input: TargetInput) -> str:
    return stable_hash(input.model_dump(mode="json", exclude={"metadata"}), 24)


class ReplayTarget(TargetAdapter):
    """Returns the recorded output for each input; errors on unknown inputs."""

    kind = "replay"
    capabilities = ALL_CAPABILITIES

    def __init__(
        self, recordings: dict[str, TargetOutput], name: str = "replay", source: str | None = None
    ) -> None:
        self.recordings = recordings
        self.name = name
        self.source = source

    async def run(self, input: TargetInput) -> TargetOutput:
        try:
            return self.recordings[_key(input)].model_copy(deep=True)
        except KeyError:
            raise LookupError("no recorded output for this input") from None

    def ref(self) -> TargetRef:
        return TargetRef(
            kind="replay", name=self.name, params={"source": self.source}, reproducible=False
        )


def load_recordings(path: str | Path) -> tuple[list[TestCase], ReplayTarget]:
    """Load ``{input, output, category?, evaluators?, reference?, ...}`` records.

    ``input`` and ``output`` may be strings or full TargetInput/TargetOutput
    objects. Records without a category get ``reliability.instruction_following``.
    """
    path = Path(path)
    text = path.read_text("utf-8")
    items: list[dict[str, Any]]
    if path.suffix == ".jsonl":
        items = [json.loads(line) for line in text.splitlines() if line.strip()]
    elif path.suffix == ".json":
        items = json.loads(text)
    else:
        items = yaml.safe_load(text) or []
    cases: list[TestCase] = []
    recordings: dict[str, TargetOutput] = {}
    for item in items:
        data = dict(item)
        output = coerce_output(data.pop("output", ""))
        data.setdefault("category", "reliability.instruction_following")
        case = TestCase.model_validate(data)
        recordings[_key(case.input)] = output
        cases.append(case)
    return cases, ReplayTarget(recordings, name=f"replay:{path.name}", source=str(path))
