"""File-based run store (``.redsi/runs/<RUN-ID>.json``).

Artifacts are plain JSON so they can be diffed, committed as CI baselines,
or loaded by other tools. Everything is passed through the redactor before
it touches disk.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from redsi.campaign.artifact import RunArtifact
from redsi.core.models import Finding
from redsi.observability.redaction import Redactor, default_redactor

DEFAULT_ROOT = ".redsi"


class RunStore:
    def __init__(self, root: str | Path = DEFAULT_ROOT, redactor: Redactor | None = None) -> None:
        self.root = Path(root)
        self.runs_dir = self.root / "runs"
        self.redactor = redactor or default_redactor()

    def path_for(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.json"

    def events_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.events.jsonl"

    def save(self, artifact: RunArtifact) -> Path:
        path = self.path_for(artifact.run_id)
        write_artifact(artifact, path, self.redactor)
        (self.root / "LATEST").write_text(artifact.run_id, "utf-8")
        return path

    def resolve(self, ref: str = "latest") -> Path:
        candidate = Path(ref)
        if candidate.suffix == ".json" and candidate.is_file():
            return candidate
        if ref == "latest":
            latest = self.root / "LATEST"
            if not latest.is_file():
                raise FileNotFoundError(f"no runs in {self.runs_dir}")
            ref = latest.read_text("utf-8").strip()
        path = self.path_for(ref)
        if path.is_file():
            return path
        matches = sorted(self.runs_dir.glob(f"{ref}*.json")) if self.runs_dir.is_dir() else []
        matches = [m for m in matches if not m.name.endswith(".events.jsonl")]
        if len(matches) == 1:
            return matches[0]
        raise FileNotFoundError(f"run {ref!r} not found in {self.runs_dir}")

    def load(self, ref: str = "latest") -> RunArtifact:
        return load_artifact(self.resolve(ref))

    def runs(self) -> list[dict[str, Any]]:
        if not self.runs_dir.is_dir():
            return []
        out = []
        for path in sorted(self.runs_dir.glob("RUN-*.json"), reverse=True):
            try:
                out.append(load_artifact(path).summary())
            except (ValueError, OSError):
                continue
        return out

    def find_finding(self, finding_id: str, run: str = "latest") -> tuple[RunArtifact, Finding]:
        artifact = self.load(run)
        return artifact, artifact.finding(finding_id)

    def update(self, artifact: RunArtifact) -> Path:
        path = self.path_for(artifact.run_id)
        write_artifact(artifact, path, self.redactor)
        return path


def write_artifact(
    artifact: RunArtifact, path: str | Path, redactor: Redactor | None = None
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (redactor or default_redactor()).obj(artifact.model_dump(mode="json"))
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def load_artifact(path: str | Path) -> RunArtifact:
    return RunArtifact.model_validate_json(Path(path).read_text("utf-8"))
