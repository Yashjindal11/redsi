"""Reports in JSON, Markdown and HTML. All output is passed through the redactor."""

from __future__ import annotations

import json
from typing import Literal

from redsi.campaign.artifact import RunArtifact
from redsi.observability.redaction import default_redactor
from redsi.regression import Comparison
from redsi.reporting.html import render_html
from redsi.reporting.markdown import render_markdown

Format = Literal["json", "markdown", "md", "html"]


def render(art: RunArtifact, fmt: Format = "markdown", comparison: Comparison | None = None) -> str:
    redactor = default_redactor()
    if fmt == "json":
        payload = {"run": art.model_dump(mode="json")}
        if comparison is not None:
            payload["comparison"] = comparison.model_dump(mode="json")
        return json.dumps(redactor.obj(payload), indent=1, ensure_ascii=False)
    if fmt in ("markdown", "md"):
        return redactor.text(render_markdown(art, comparison))
    if fmt == "html":
        return redactor.text(render_html(art, comparison))
    raise ValueError(f"unknown report format {fmt!r}")


__all__ = ["render", "render_html", "render_markdown"]
