import json

import pytest

from redsi import RedSI, Target, TestCase
from redsi.evaluators import NotContains, NumericAnswer
from redsi.regression import compare
from redsi.reporting import render

CASES = [
    TestCase(
        input="2+2?", category="reasoning.arithmetic", reference="4", evaluators=[NumericAnswer()]
    ),
    TestCase(
        input="Show <script>alert(1)</script> code",
        category="security.data_leakage",
        evaluators=[NotContains(texts=["CANARY"])],
    ),
]


def target(prompt: str) -> str:
    return "5" if "2+2" in prompt else "CANARY <b>leaked</b> | pipe"


@pytest.fixture
async def art():
    return await RedSI(Target.from_function(target, name="demo"), store=None).run(
        tests=CASES, mode="custom", name="demo run"
    )


SECTIONS = [
    "Executive summary",
    "Target",
    "Evaluation configuration",
    "Test coverage",
    "Overall results",
    "Failure distribution",
    "Critical findings",
    "Detailed findings",
    "Reproduction instructions",
    "Regression analysis",
    "Recommendations",
    "Raw artifacts",
]


async def test_markdown_has_all_sections_and_honesty_statements(art) -> None:
    md = render(art, "markdown")
    for s in SECTIONS:
        assert f"## {s}" in md, s
    assert "not evidence that the system is safe" in md
    assert "hypothesis, not observed fact" in md
    assert f"redsi reproduce FINDING-001 --run {art.run_id}" in md
    assert "| pipe" in md  # output text is kept verbatim inside a code fence


async def test_html_escapes_untrusted_content(art) -> None:
    html = render(art, "html")
    for s in SECTIONS:
        assert s in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>leaked</b>" not in html


async def test_json_report_includes_comparison(art) -> None:
    data = json.loads(render(art, "json", comparison=compare(art, art)))
    assert data["run"]["run_id"] == art.run_id
    assert data["comparison"]["shared"] == 2


async def test_reports_are_redacted(art, monkeypatch) -> None:
    monkeypatch.setenv("SOME_API_KEY", "abcd-secret-value-123")
    art.findings[0].output.text = "token abcd-secret-value-123"
    for fmt in ("markdown", "html", "json"):
        assert "abcd-secret-value-123" not in render(art, fmt)


async def test_unknown_format(art) -> None:
    with pytest.raises(ValueError):
        render(art, "pdf")  # type: ignore[arg-type]
