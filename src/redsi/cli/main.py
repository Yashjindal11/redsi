"""``redsi`` command-line interface.

Exit codes: 0 success, 1 quality gate failed, 2 usage or configuration error.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from redsi._version import __version__
from redsi.campaign import CampaignRunner, RunArtifact, new_run_id
from redsi.cli import render as ui
from redsi.config import (
    DEFAULT_CONFIG,
    TEMPLATE_AGENT,
    TEMPLATE_CONFIG,
    TEMPLATE_SPEC,
    ProjectConfig,
)
from redsi.core.models import FindingStatus, TestCase
from redsi.core.taxonomy import categories
from redsi.fuzzing import Fuzzer
from redsi.observability.events import CallbackSink, Event, EventBus, EventType, JsonlSink
from redsi.regression import compare, evaluate_gate
from redsi.reporting import render
from redsi.reproduce import reproduce as do_reproduce
from redsi.spec import Specification, SpecificationGenerator, unverifiable_requirements
from redsi.store import RunStore
from redsi.suites import list_suites, load_tests, resolve_suites
from redsi.targets import target_kinds
from redsi.targets.replay import load_recordings

app = typer.Typer(
    name="redsi",
    help="RedSI - systematically discover, reproduce, measure and prevent failures in AI systems.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)

ConfigOpt = Annotated[
    Path | None,
    typer.Option(
        "--config", "-c", help=f"Project config (default: ./{DEFAULT_CONFIG} if present)."
    ),
]
JsonOpt = Annotated[bool, typer.Option("--json", help="Machine-readable JSON on stdout.")]
RunOpt = Annotated[str, typer.Option("--run", "-r", help="Run id, artifact path, or 'latest'.")]


def _fail(message: str, code: int = 2) -> typer.Exit:
    ui.err.print(f"[red]error:[/] {message}")
    return typer.Exit(code)


def _load_config(path: Path | None) -> ProjectConfig:
    try:
        return ProjectConfig.load(path)
    except Exception as exc:
        raise _fail(f"invalid config: {exc}") from exc


def _emit_json(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, indent=1, default=str) + "\n")


def _version(value: bool) -> None:
    if value:
        ui.console.print(f"redsi {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    """Use RedSI only on systems you own or are authorised to test."""


# --------------------------------------------------------------------- init


@app.command()
def init(
    directory: Annotated[Path, typer.Argument(help="Where to create the project files.")] = Path(
        "."
    ),
    force: Annotated[bool, typer.Option(help="Overwrite existing files.")] = False,
) -> None:
    """Create redsi.yaml, a toy target (my_agent.py) and a specification (system.yaml)."""
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        DEFAULT_CONFIG: TEMPLATE_CONFIG,
        "my_agent.py": TEMPLATE_AGENT,
        "system.yaml": TEMPLATE_SPEC,
    }
    for name, content in files.items():
        path = directory / name
        if path.exists() and not force:
            ui.console.print(f"[yellow]skip[/] {path} (exists; use --force to overwrite)")
            continue
        path.write_text(content, "utf-8")
        ui.console.print(f"[green]create[/] {path}")
    gitignore = directory / ".gitignore"
    if not gitignore.exists() or ".redsi/" not in gitignore.read_text("utf-8"):
        with gitignore.open("a", encoding="utf-8") as fh:
            fh.write("\n.redsi/\n")
    ui.console.print(
        "\nNext: [bold]redsi test[/]  then  [bold]redsi report --format html --out report.html[/]"
    )


# --------------------------------------------------------------------- test


def _progress_bus(
    store: RunStore | None, run_id: str, quiet: bool
) -> tuple[EventBus, Progress | None]:
    sinks: list[Any] = []
    if store is not None:
        sinks.append(JsonlSink(store.events_path(run_id)))
    progress: Progress | None = None
    if not quiet:
        progress = Progress(
            TextColumn("[bold red]redsi[/]"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("{task.fields[status]}"),
            TimeElapsedColumn(),
            console=ui.err,
            transient=True,
        )
        task = progress.add_task("tests", total=None, status="")
        counts = {"pass": 0, "fail": 0}

        def on_event(e: Event) -> None:
            assert progress is not None
            if e.type == EventType.CAMPAIGN_STARTED:
                progress.update(task, total=e.data.get("tests"))
            elif e.type == EventType.GENERATION_FINISHED and e.data.get("generator") == "fuzzer":
                current = progress.tasks[0].total or 0
                progress.update(task, total=current + int(e.data.get("tests", 0)))
            elif e.type in (EventType.CASE_FINISHED, EventType.CASE_SKIPPED):
                v = e.data.get("verdict")
                if v in counts:
                    counts[v] += 1
                progress.update(
                    task,
                    advance=1,
                    status=f"[green]{counts['pass']} pass[/] [red]{counts['fail']} fail[/]",
                )

        sinks.append(CallbackSink(on_event))
    return EventBus(sinks, run_id=run_id), progress


@app.command()
def test(
    target: Annotated[
        str | None,
        typer.Argument(
            help="file.py[:fn], pkg.module:fn, https://url, or openai:<model>. Defaults to 'target' in redsi.yaml."
        ),
    ] = None,
    suite: Annotated[
        list[str] | None,
        typer.Option("--suite", "-s", help="Suite name, 'all', or a tests file. Repeatable."),
    ] = None,
    spec: Annotated[Path | None, typer.Option(help="Specification YAML.")] = None,
    tests: Annotated[
        list[Path] | None,
        typer.Option("--tests", "-t", help="Extra tests file (yaml/json/jsonl). Repeatable."),
    ] = None,
    mode: Annotated[str | None, typer.Option(help="quick | standard | deep | custom")] = None,
    category: Annotated[
        list[str] | None,
        typer.Option("--category", help="Only categories matching this glob. Repeatable."),
    ] = None,
    judge: Annotated[
        list[str] | None,
        typer.Option("--judge", "-j", help="Judge model, e.g. openai:gpt-4o-mini. Repeatable."),
    ] = None,
    generator: Annotated[
        str | None, typer.Option(help="Generator model for paraphrases/probes.")
    ] = None,
    spec_probes: Annotated[
        int, typer.Option(help="LLM-generated probes per requirement (needs --generator).")
    ] = 0,
    fuzz: Annotated[
        bool | None, typer.Option("--fuzz/--no-fuzz", help="Override the mode's fuzzing setting.")
    ] = None,
    concurrency: Annotated[int | None, typer.Option(help="Parallel target calls.")] = None,
    max_cases: Annotated[int | None, typer.Option(help="Maximum tests to run.")] = None,
    max_cost: Annotated[
        float | None, typer.Option(help="Stop when spend reaches this many USD.")
    ] = None,
    max_failures: Annotated[int | None, typer.Option(help="Stop after this many failures.")] = None,
    samples: Annotated[int | None, typer.Option(help="Samples per test.")] = None,
    seed: Annotated[int | None, typer.Option(help="Random seed for generation.")] = None,
    timeout: Annotated[float | None, typer.Option(help="Per-call timeout in seconds.")] = None,
    isolate: Annotated[
        bool | None,
        typer.Option("--isolate/--no-isolate", help="Run Python targets in a killable subprocess."),
    ] = None,
    name: Annotated[str | None, typer.Option(help="Human-readable run name.")] = None,
    baseline: Annotated[
        str | None, typer.Option(help="Baseline run id or artifact path to compare against.")
    ] = None,
    min_pass_rate: Annotated[
        float | None, typer.Option(help="Gate: minimum pass rate (0-1).")
    ] = None,
    max_critical: Annotated[
        int | None, typer.Option(help="Gate: maximum confirmed/likely critical findings.")
    ] = None,
    max_regressions: Annotated[
        int | None, typer.Option(help="Gate: maximum regressions vs baseline.")
    ] = None,
    no_gate: Annotated[bool, typer.Option("--no-gate", help="Always exit 0.")] = False,
    report: Annotated[
        Path | None, typer.Option(help="Also write a report (.md, .html or .json).")
    ] = None,
    out: Annotated[
        Path | None, typer.Option(help="Also copy the run artifact here (e.g. baseline.json).")
    ] = None,
    config: ConfigOpt = None,
    as_json: JsonOpt = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q")] = False,
) -> None:
    """Run a test campaign against a target."""
    cfg = _load_config(config)
    try:
        tgt = cfg.build_target(target, isolate=isolate)
        models = cfg.build_models(judge, generator)
        campaign = cfg.campaign_config(
            mode=mode,
            concurrency=concurrency,
            max_cases=max_cases,
            max_cost_usd=max_cost,
            max_failures=max_failures,
            samples=samples,
            seed=seed,
            timeout=timeout,
            categories=category,
        )
    except Exception as exc:
        raise _fail(str(exc)) from exc
    if fuzz is False:
        campaign.fuzz = False
    elif fuzz and not isinstance(campaign.fuzz, dict):
        campaign.fuzz = True

    store = RunStore(cfg.store)
    run_id = new_run_id()
    bus, progress = _progress_bus(store, run_id, quiet or as_json)

    async def go() -> RunArtifact:
        cases: list[TestCase] = []
        spec_path = spec or (Path(cfg.resolve_path(cfg.spec)) if cfg.spec and not suite else None)
        spec_summary = None
        req_ids = None
        if spec_path:
            spec_obj = Specification.load(spec_path)
            cases += await SpecificationGenerator(spec_probes).generate(
                spec_obj, models, seed=campaign.seed, bus=bus
            )
            req_ids = [r.id for r in spec_obj.requirements]
            spec_summary = {
                **spec_obj.summary(),
                "unverifiable": unverifiable_requirements(spec_obj, bool(models.judges)),
            }
        for t in [*(tests or []), *[Path(cfg.resolve_path(p)) for p in cfg.tests]]:
            cases += load_tests(t)
        names = list(suite or []) or (cfg.suites if not spec else []) or ([] if cases else ["all"])
        campaign.suites = names
        cases = resolve_suites(names) + cases
        runner = CampaignRunner(tgt, campaign, models=models, bus=bus, run_id=run_id)
        try:
            return await runner.run(cases, name=name, spec=spec_summary, requirement_ids=req_ids)
        finally:
            await tgt.aclose()
            await models.aclose()

    try:
        if progress is not None:
            with progress:
                art = asyncio.run(go())
        else:
            art = asyncio.run(go())
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise _fail(str(exc)) from exc

    path = store.save(art)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(path.read_text("utf-8"), "utf-8")

    cmp = None
    if baseline:
        try:
            cmp = compare(store.load(baseline), art)
        except FileNotFoundError as exc:
            raise _fail(str(exc)) from exc
    gate_cfg = cfg.gate.model_copy(
        update={
            k: v
            for k, v in {
                "min_pass_rate": min_pass_rate,
                "max_critical": max_critical,
                "max_regressions": max_regressions,
            }.items()
            if v is not None
        }
    )
    gate = evaluate_gate(art, gate_cfg, cmp)
    if report:
        _write_report(art, report, cmp)

    if as_json:
        _emit_json(
            {
                "run": art.summary(),
                "artifact": str(path),
                "findings": [
                    {
                        "id": f.id,
                        "severity": f.severity.value,
                        "status": f.status.value,
                        "category": f.category,
                        "title": f.title,
                    }
                    for f in art.findings
                ],
                "comparison": cmp.model_dump(mode="json") if cmp else None,
                "gate": gate.model_dump(mode="json"),
            }
        )
    else:
        ui.run_summary(art)
        ui.findings_table(art.findings)
        if cmp:
            ui.comparison(cmp)
        ui.gate(gate)
        ui.console.print(f"[dim]artifact: {path}[/]")
    if not gate.passed and not no_gate:
        raise typer.Exit(1)


def _write_report(art: RunArtifact, path: Path, cmp: Any = None) -> None:
    fmt = {".html": "html", ".htm": "html", ".json": "json"}.get(path.suffix, "markdown")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(art, fmt, cmp), "utf-8")  # type: ignore[arg-type]
    ui.err.print(f"[dim]report: {path}[/]")


# ----------------------------------------------------------------- generate


@app.command()
def generate(
    spec: Annotated[Path | None, typer.Option(help="Specification YAML to generate from.")] = None,
    suite: Annotated[
        list[str] | None,
        typer.Option("--suite", "-s", help="Use suite tests as seeds. Repeatable."),
    ] = None,
    count: Annotated[int, typer.Option(help="Target number of tests (seeds + variants).")] = 50,
    strategy: Annotated[
        list[str] | None, typer.Option("--strategy", help="Mutation strategy. Repeatable.")
    ] = None,
    generator: Annotated[
        str | None, typer.Option(help="Generator model for paraphrases/probes.")
    ] = None,
    spec_probes: Annotated[int, typer.Option(help="LLM-generated probes per requirement.")] = 0,
    seed: Annotated[int, typer.Option()] = 0,
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Output file (.jsonl, .json or .yaml).")
    ] = Path("tests.jsonl"),
    config: ConfigOpt = None,
) -> None:
    """Generate test cases (without running them) for review or later use with --tests."""
    cfg = _load_config(config)
    models = cfg.build_models(None, generator)

    async def go() -> list[TestCase]:
        seeds: list[TestCase] = []
        if spec:
            seeds += await SpecificationGenerator(spec_probes).generate(
                Specification.load(spec), models, seed=seed
            )
        if suite:
            seeds += resolve_suites(suite)
        if not seeds:
            raise ValueError("nothing to generate from: pass --spec and/or --suite")
        cases = list(seeds)
        fuzzer = Fuzzer(strategy or None, per_seed=2, seed=seed, models=models)
        round_index = 0
        while len(cases) < count and round_index < 20:
            seen = {c.id for c in cases}
            new = [
                v for v in await fuzzer.generate(seeds, round_index=round_index) if v.id not in seen
            ]
            cases += new[: count - len(cases)]
            round_index += 1
        await models.aclose()
        return cases[:count]

    try:
        cases = asyncio.run(go())
    except (ValueError, KeyError, FileNotFoundError) as exc:
        raise _fail(str(exc)) from exc
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [c.model_dump(mode="json", exclude_defaults=True) for c in cases]
    if out.suffix == ".jsonl":
        out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    elif out.suffix == ".json":
        out.write_text(json.dumps(rows, indent=1, ensure_ascii=False), "utf-8")
    else:
        import yaml

        out.write_text(yaml.safe_dump(rows, sort_keys=False, allow_unicode=True), "utf-8")
    by_strategy: dict[str, int] = {}
    for c in cases:
        key = (
            " -> ".join(c.origin.strategies)
            if c.origin and c.origin.strategies
            else (c.origin.generator if c.origin else "suite")
        )
        by_strategy[key] = by_strategy.get(key, 0) + 1
    ui.kv_table(f"Generated {len(cases)} tests -> {out}", sorted(by_strategy.items()))


# ----------------------------------------------------------------- evaluate


@app.command()
def evaluate(
    records: Annotated[
        Path,
        typer.Argument(
            help="Recorded {input, output, category?, evaluators?, reference?} items (jsonl/json/yaml)."
        ),
    ],
    judge: Annotated[list[str] | None, typer.Option("--judge", "-j")] = None,
    name: Annotated[str | None, typer.Option()] = None,
    config: ConfigOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Evaluate pre-recorded outputs (e.g. production logs) without calling a live system."""
    cfg = _load_config(config)
    try:
        cases, target = load_recordings(records)
    except Exception as exc:
        raise _fail(f"cannot read {records}: {exc}") from exc
    models = cfg.build_models(judge, None)
    store = RunStore(cfg.store)
    campaign = cfg.campaign_config(mode="custom", fuzz=False, retries=0)
    runner = CampaignRunner(target, campaign, models=models)
    art = asyncio.run(runner.run(cases, name=name or f"evaluate {records.name}"))
    path = store.save(art)
    if as_json:
        _emit_json({"run": art.summary(), "artifact": str(path)})
    else:
        ui.run_summary(art)
        ui.findings_table(art.findings)


# ---------------------------------------------------------------- reproduce


@app.command()
def reproduce(
    finding: Annotated[str, typer.Argument(help="Finding id, e.g. FINDING-001.")],
    run: RunOpt = "latest",
    attempts: Annotated[int, typer.Option(min=1, max=50)] = 3,
    target: Annotated[
        str | None, typer.Option(help="Target override if the stored one cannot be rebuilt.")
    ] = None,
    config: ConfigOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Re-run a finding and record how often it reproduces."""
    cfg = _load_config(config)
    store = RunStore(cfg.store)
    try:
        art = store.load(run)
        art.finding(finding)
        tgt = cfg.build_target(target) if target else None
    except (FileNotFoundError, KeyError, ValueError) as exc:
        raise _fail(str(exc)) from exc
    models = cfg.build_models()
    try:
        result = asyncio.run(
            do_reproduce(art, finding, target=tgt, attempts=attempts, models=models)
        )
    except ValueError as exc:
        raise _fail(f"{exc} (use --target)") from exc
    store.update(art)
    if as_json:
        _emit_json(result.model_dump(mode="json") | {"rate": result.rate})
        return
    style = "red" if result.reproduced else "green"
    ui.console.print(
        f"[{style}]{result.failures}/{result.attempts}[/] attempts failed for {finding}"
        + (" [yellow](flaky)[/]" if result.flaky else "")
    )
    if result.status_after != result.status_before:
        ui.console.print(
            f"status: {result.status_before.value} -> [bold]{result.status_after.value}[/]"
        )
    for w in result.warnings:
        ui.console.print(f"[yellow]warning:[/] {w}")


# ------------------------------------------------------------------ compare


@app.command(name="compare")
def compare_cmd(
    baseline: Annotated[str, typer.Argument(help="Baseline run id or artifact path.")],
    candidate: Annotated[str, typer.Argument(help="Candidate run id or artifact path.")] = "latest",
    min_pass_rate: Annotated[float | None, typer.Option()] = None,
    max_regressions: Annotated[int | None, typer.Option()] = None,
    max_critical: Annotated[int | None, typer.Option()] = None,
    config: ConfigOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Compare two runs: regressions, resolved failures, pass-rate and coverage change."""
    cfg = _load_config(config)
    store = RunStore(cfg.store)
    try:
        a, b = store.load(baseline), store.load(candidate)
    except FileNotFoundError as exc:
        raise _fail(str(exc)) from exc
    cmp = compare(a, b)
    updates = {
        k: v
        for k, v in {
            "min_pass_rate": min_pass_rate,
            "max_regressions": max_regressions,
            "max_critical": max_critical,
        }.items()
        if v is not None
    }
    gate = evaluate_gate(b, cfg.gate.model_copy(update=updates), cmp)
    if as_json:
        _emit_json(
            {"comparison": cmp.model_dump(mode="json"), "gate": gate.model_dump(mode="json")}
        )
    else:
        ui.comparison(cmp)
        ui.gate(gate)
    if not gate.passed:
        raise typer.Exit(1)


# ------------------------------------------------------------------- report


@app.command()
def report(
    run: Annotated[str, typer.Argument(help="Run id, artifact path, or 'latest'.")] = "latest",
    fmt: Annotated[str, typer.Option("--format", "-f", help="markdown | html | json")] = "markdown",
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Output file (default: stdout).")
    ] = None,
    baseline: Annotated[
        str | None, typer.Option(help="Include regression analysis against this run.")
    ] = None,
    config: ConfigOpt = None,
) -> None:
    """Render a run as a Markdown, HTML or JSON report."""
    cfg = _load_config(config)
    store = RunStore(cfg.store)
    try:
        art = store.load(run)
        cmp = compare(store.load(baseline), art) if baseline else None
        text = render(art, fmt, cmp)  # type: ignore[arg-type]
    except (FileNotFoundError, ValueError) as exc:
        raise _fail(str(exc)) from exc
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, "utf-8")
        ui.err.print(f"report: {out}")
    else:
        sys.stdout.write(text + "\n")


# ------------------------------------------------------------------ inspect


@app.command()
def inspect(
    ref: Annotated[
        str, typer.Argument(help="Run id / path / 'latest', or a finding id like FINDING-003.")
    ] = "latest",
    run: RunOpt = "latest",
    status: Annotated[str | None, typer.Option(help="Filter findings by status.")] = None,
    severity: Annotated[str | None, typer.Option(help="Filter findings by severity.")] = None,
    config: ConfigOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Show a run summary and its findings, or the full detail of one finding."""
    cfg = _load_config(config)
    store = RunStore(cfg.store)
    try:
        if ref.upper().startswith("FINDING-"):
            art, f = store.find_finding(ref.upper(), run)
            if as_json:
                _emit_json(f.model_dump(mode="json"))
            else:
                ui.finding_detail(art, f)
            return
        art = store.load(ref)
    except (FileNotFoundError, KeyError) as exc:
        raise _fail(str(exc)) from exc
    findings = [
        f
        for f in art.findings
        if (not status or f.status.value == status)
        and (not severity or f.severity.value == severity)
    ]
    if as_json:
        _emit_json(
            {
                "run": art.summary(),
                "metrics": art.metrics.model_dump(mode="json"),
                "findings": [f.model_dump(mode="json") for f in findings],
            }
        )
        return
    ui.run_summary(art)
    ui.findings_table(findings, limit=100)


@app.command()
def runs(config: ConfigOpt = None, as_json: JsonOpt = False) -> None:
    """List stored runs, newest first."""
    store = RunStore(_load_config(config).store)
    items = store.runs()
    if as_json:
        _emit_json(items)
        return
    from rich.table import Table

    t = Table(title=f"Runs in {store.runs_dir}")
    for col in ("Run", "Name", "Target", "Tests", "Pass rate", "Findings"):
        t.add_column(col)
    for r in items:
        rate = "-" if r["pass_rate"] is None else f"{r['pass_rate']:.1%}"
        sev = ", ".join(f"{v} {k}" for k, v in r["findings"].items()) or "-"
        t.add_row(r["run_id"], r["name"] or "", r["target"], str(r["tests"]), rate, sev)
    ui.console.print(t)


@app.command()
def triage(
    finding: Annotated[str, typer.Argument()],
    status: Annotated[FindingStatus, typer.Option(help="New status, e.g. false_positive.")],
    note: Annotated[str | None, typer.Option(help="Why (recorded in the artifact).")] = None,
    run: RunOpt = "latest",
    config: ConfigOpt = None,
) -> None:
    """Record a human review decision on a finding (e.g. mark a false positive)."""
    store = RunStore(_load_config(config).store)
    try:
        art, f = store.find_finding(finding.upper(), run)
    except (FileNotFoundError, KeyError) as exc:
        raise _fail(str(exc)) from exc
    before = f.status
    f.status = status
    f.notes.append(
        f"human review: {before.value} -> {status.value}" + (f" ({note})" if note else "")
    )
    store.update(art)
    ui.console.print(f"{f.id}: {before.value} -> [bold]{status.value}[/]")


# ----------------------------------------------------------- catalogue info


@app.command(name="suites")
def suites_cmd(
    show_categories: Annotated[
        bool, typer.Option("--categories", help="Show the failure taxonomy instead.")
    ] = False,
    as_json: JsonOpt = False,
) -> None:
    """List built-in and installed test suites (or the failure taxonomy)."""
    from rich.table import Table

    if show_categories:
        cats = categories()
        if as_json:
            _emit_json(
                [
                    {"id": c.id, "severity": c.default_severity.value, "description": c.description}
                    for c in cats
                ]
            )
            return
        t = Table(title="Failure taxonomy")
        for col in ("Category", "Default severity", "Description"):
            t.add_column(col)
        for c in cats:
            t.add_row(c.id, ui.sev(c.default_severity.value), c.description)
        ui.console.print(t)
        return
    rows = [
        (s.name, len(s.cases()), sorted({c.category for c in s.cases()}), s.description)
        for s in list_suites()
    ]
    if as_json:
        _emit_json(
            [{"name": n, "tests": k, "categories": c, "description": d} for n, k, c, d in rows]
        )
        return
    t = Table(title="Suites")
    for col in ("Suite", "Tests", "Categories", "Description"):
        t.add_column(col, overflow="fold")
    for n, k, cats_, d in rows:
        t.add_row(n, str(k), str(len(cats_)), d)
    ui.console.print(t)


@app.command()
def targets() -> None:
    """Show supported target kinds and how to reference them."""
    ui.kv_table(
        "Target kinds",
        [
            (
                "python file",
                "my_agent.py[:function]   (function(prompt) -> str | dict | TargetOutput)",
            ),
            ("python module", "package.module:function"),
            ("isolated", "--isolate: each call in a separate process, killed on timeout"),
            ("http", "https://host/path   (configure body/response_path in redsi.yaml)"),
            (
                "chat model",
                "openai:<model>, anthropic:<model>, ollama:<model>, gemini:<model>, huggingface:<model>",
            ),
            ("custom", "subclass redsi.TargetAdapter and export it as redsi_target"),
            ("registered kinds", ", ".join(target_kinds.names())),
        ],
    )


@app.command(name="config")
def config_cmd(
    action: Annotated[str, typer.Argument(help="show | validate")] = "show",
    config: ConfigOpt = None,
) -> None:
    """Show or validate the project configuration."""
    cfg = _load_config(config)
    if action == "validate":
        problems = []
        if cfg.target is None:
            problems.append("no target set")
        try:
            resolve_suites(cfg.suites)
        except KeyError as exc:
            problems.append(str(exc))
        if cfg.spec:
            try:
                Specification.load(cfg.resolve_path(cfg.spec))
            except Exception as exc:
                problems.append(f"spec: {exc}")
        if problems:
            for p in problems:
                ui.console.print(f"[red]x[/] {p}")
            raise typer.Exit(2)
        ui.console.print("[green]configuration is valid[/]")
        return
    _emit_json(cfg.model_dump(mode="json"))


if __name__ == "__main__":  # pragma: no cover
    app()
