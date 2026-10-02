import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from redsi.cli.main import app

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    return tmp_path


def invoke(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.stdout


def test_init_creates_files_and_does_not_overwrite(project: Path) -> None:
    assert {"redsi.yaml", "my_agent.py", "system.yaml"} <= {p.name for p in project.iterdir()}
    code, out = invoke("init")
    assert code == 0 and "skip" in out
    assert ".redsi/" in (project / ".gitignore").read_text()


def test_test_command_finds_leak_and_fails_gate(project: Path) -> None:
    code, out = invoke("test", "--quiet", "--json")
    data = json.loads(out)
    assert code == 1, "critical leak must fail the default gate"
    assert not data["gate"]["passed"]
    assert any(
        f["category"] == "security.data_leakage" and f["severity"] == "critical"
        for f in data["findings"]
    )
    code, _ = invoke("test", "--quiet", "--json", "--no-gate")
    assert code == 0


def test_inspect_reproduce_report_compare_triage(project: Path) -> None:
    invoke("test", "--quiet", "--no-gate", "--suite", "reasoning", "--mode", "quick")
    code, out = invoke("inspect", "--json")
    assert code == 0 and json.loads(out)["run"]["tests"] == 12

    code, out = invoke("inspect", "FINDING-001", "--json")
    assert code == 0 and json.loads(out)["id"] == "FINDING-001"

    code, out = invoke("reproduce", "FINDING-001", "--attempts", "2", "--json")
    assert code == 0 and json.loads(out)["failures"] == 2

    code, _ = invoke("report", "--format", "html", "--out", "r.html")
    assert code == 0 and "<html" in (project / "r.html").read_text()

    baseline = next((project / ".redsi" / "runs").glob("RUN-*.json"))
    invoke("test", "--quiet", "--no-gate", "--suite", "reasoning", "--mode", "quick")
    code, out = invoke("compare", str(baseline), "latest", "--json")
    data = json.loads(out)
    assert data["comparison"]["shared"] == 12 and data["comparison"]["regressions"] == []

    code, out = invoke("triage", "FINDING-001", "--status", "false_positive", "--note", "reviewed")
    assert code == 0 and "false_positive" in out
    code, out = invoke("inspect", "FINDING-001", "--json")
    assert json.loads(out)["status"] == "false_positive"


def test_baseline_gate_detects_regression(project: Path) -> None:
    agent = project / "my_agent.py"
    invoke(
        "test",
        "--quiet",
        "--no-gate",
        "--suite",
        "robustness",
        "--mode",
        "quick",
        "--out",
        "baseline.json",
    )
    agent.write_text(agent.read_text().replace('return "Paris."', 'return "Lyon."'))
    code, out = invoke(
        "test",
        "--quiet",
        "--json",
        "--suite",
        "robustness",
        "--mode",
        "quick",
        "--baseline",
        "baseline.json",
    )
    data = json.loads(out)
    assert code == 1
    assert len(data["comparison"]["regressions"]) >= 1
    assert any("regressions" in v for v in data["gate"]["violations"])


def test_evaluate_recorded_outputs(project: Path) -> None:
    logs = project / "logs.jsonl"
    logs.write_text(
        json.dumps(
            {
                "input": "2+2?",
                "output": "5",
                "category": "reasoning.arithmetic",
                "reference": "4",
                "evaluators": [{"type": "numeric_answer"}],
            }
        )
        + "\n"
    )
    code, out = invoke("evaluate", str(logs), "--json")
    assert code == 0 and json.loads(out)["run"]["failed"] == 1


def test_generate_writes_tests_with_lineage(project: Path) -> None:
    code, _ = invoke("generate", "--spec", "system.yaml", "--count", "15", "--out", "gen.jsonl")
    assert code == 0
    rows = [json.loads(line) for line in (project / "gen.jsonl").read_text().splitlines()]
    assert len(rows) == 15
    assert any(r.get("origin", {}).get("strategies") for r in rows)


def test_catalogue_commands(project: Path) -> None:
    code, out = invoke("suites", "--json")
    assert code == 0 and {s["name"] for s in json.loads(out)} >= {"security", "rag"}
    code, out = invoke("suites", "--categories", "--json")
    assert code == 0 and len(json.loads(out)) >= 35
    assert invoke("targets")[0] == 0
    assert invoke("config", "validate")[0] == 0


def test_usage_errors_exit_2(project: Path) -> None:
    assert invoke("inspect", "RUN-does-not-exist")[0] == 2
    assert invoke("test", "--suite", "nope", "--quiet")[0] == 2
    assert invoke("test", "missing_file.py", "--quiet")[0] == 2
