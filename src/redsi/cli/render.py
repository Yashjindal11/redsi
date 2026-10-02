"""Human-readable terminal output (rich)."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from redsi.campaign.artifact import RunArtifact
from redsi.core.models import Finding
from redsi.regression import Comparison, GateResult

console = Console()
err = Console(stderr=True)

SEV_STYLE = {
    "critical": "bold white on red",
    "high": "bold red",
    "medium": "yellow",
    "low": "cyan",
    "info": "dim",
}
VERDICT_STYLE = {
    "pass": "green",
    "fail": "red",
    "uncertain": "yellow",
    "error": "magenta",
    "skip": "dim",
}


def sev(s: str) -> str:
    return f"[{SEV_STYLE.get(s, '')}]{s}[/]"


def run_summary(art: RunArtifact) -> None:
    m = art.metrics
    rate = "-" if m.pass_rate is None else f"{m.pass_rate:.1%}"
    t = Table.grid(padding=(0, 2))
    t.add_row("Run", f"[bold]{art.run_id}[/]", "Target", art.target.name)
    t.add_row("Tests", str(m.total), "Pass rate", rate)
    t.add_row("[green]Passed[/]", str(m.passed), "[red]Failed[/]", str(m.failed))
    t.add_row(
        "[yellow]Uncertain[/]", str(m.uncertain), "Errors / skipped", f"{m.errors} / {m.skipped}"
    )
    cost = m.total_cost_usd
    t.add_row(
        "Coverage",
        f"{art.coverage.taxonomy_fraction:.0%} of taxonomy",
        "Cost",
        "unknown" if cost is None else f"${cost:.4f}",
    )
    t.add_row(
        "Latency p50/p95",
        f"{m.latency_ms_p50 or '-'} / {m.latency_ms_p95 or '-'} ms",
        "Duration",
        f"{m.duration_s:.1f}s",
    )
    console.print(Panel(t, title="RedSI", border_style="red"))
    if art.stopped_reason:
        console.print(f"[yellow]Stopped early:[/] {art.stopped_reason}")
    if art.spec and art.spec.get("unverifiable"):
        console.print(
            f"[yellow]{len(art.spec['unverifiable'])} requirement(s) could not be verified[/] "
            "(no deterministic check and no judge model): " + ", ".join(art.spec["unverifiable"])
        )


def findings_table(findings: list[Finding], limit: int = 25) -> None:
    if not findings:
        console.print("[green]No findings.[/]")
        return
    t = Table(title=f"Findings ({len(findings)})", show_lines=False)
    for col in ("ID", "Severity", "Status", "Category", "Input", "Why"):
        t.add_column(col, overflow="fold")
    for f in findings[:limit]:
        t.add_row(
            f.id,
            sev(f.severity.value),
            f.status.value,
            f.category,
            escape(" ".join(f.input.prompt.split())[:60]),
            escape(f.explanation[:80]),
        )
    console.print(t)
    if len(findings) > limit:
        console.print(f"[dim]... {len(findings) - limit} more (redsi inspect / redsi report)[/]")


def finding_detail(art: RunArtifact, f: Finding) -> None:
    t = Table.grid(padding=(0, 2))
    t.add_row("Severity", sev(f.severity.value), "Status", f"{f.status.value} ({f.confidence:.2f})")
    t.add_row("Category", f.category, "Test", f.case_id)
    if f.origin and f.origin.strategies:
        t.add_row(
            "Mutations", " -> ".join(f.origin.strategies), "Parent", f.origin.parent_id or "-"
        )
    if f.reproducibility and f.reproducibility.attempts:
        r = f.reproducibility
        t.add_row("Reproduced", f"{r.failures}/{r.attempts}", "Flaky", str(r.flaky))
    console.print(Panel(t, title=escape(f"{f.id}  {f.title}"), border_style="red"))
    console.print("[bold]Input[/]")
    console.print(f.input.prompt, markup=False)
    if f.input.system:
        console.print("[bold]System[/]")
        console.print(f.input.system, markup=False)
    console.print("[bold]Observed output[/]")
    console.print(f.output.text or f.output.error or "", markup=False)
    for c in f.output.tool_calls:
        console.print(f"  tool call: {c.name}({c.arguments})", markup=False)
    console.print(f"[bold]Expected:[/] {escape(f.expected or '-')}")
    console.print(f"[bold]Why it failed (observed):[/] {escape(f.explanation)}")
    for res in f.results:
        style = VERDICT_STYLE.get(res.verdict.value, "")
        console.print(
            f"  [{style}]{res.verdict.value:9}[/] {escape(res.evaluator)} ({res.confidence:.2f}) "
            f"{escape(res.explanation[:120])}"
        )
    console.print("[bold]Inferred root cause[/] [dim](hypothesis)[/]")
    for h in f.hypotheses:
        console.print(f"  {h.cause.value} ({h.likelihood}) {'; '.join(h.evidence)}", markup=False)
    for n in f.notes:
        console.print(f"[dim]note: {escape(n)}[/]")
    console.print(f"[dim]reproduce: redsi reproduce {f.id} --run {art.run_id}[/]")


def comparison(cmp: Comparison) -> None:
    t = Table(title=f"{cmp.baseline_run} -> {cmp.candidate_run}")
    t.add_column("Metric")
    t.add_column("Value", justify="right")
    before = "-" if cmp.pass_rate_before is None else f"{cmp.pass_rate_before:.1%}"
    after = "-" if cmp.pass_rate_after is None else f"{cmp.pass_rate_after:.1%}"
    t.add_row("Pass rate", f"{before} -> {after}")
    t.add_row("Shared / added / removed tests", f"{cmp.shared} / {cmp.added} / {cmp.removed}")
    t.add_row("[red]Regressions[/]", str(len(cmp.regressions)))
    t.add_row("[green]Resolved[/]", str(len(cmp.resolved)))
    t.add_row("Persistent failures", str(len(cmp.persistent)))
    t.add_row("New failures", str(len(cmp.new_failures)))
    t.add_row("Newly uncertain", str(len(cmp.newly_uncertain)))
    t.add_row("Coverage", f"{cmp.coverage_before:.0%} -> {cmp.coverage_after:.0%}")
    console.print(t)
    for r in cmp.regressions[:20]:
        console.print(f"  [red]regressed[/] {r.category}: {escape(r.prompt)}")
    for w in cmp.warnings:
        console.print(f"[yellow]warning:[/] {escape(w)}")


def gate(result: GateResult) -> None:
    if result.passed:
        console.print(f"[green]Gate passed[/] ({'; '.join(result.checked) or 'no checks'})")
    else:
        console.print("[bold red]Gate failed[/]")
        for v in result.violations:
            console.print(f"  - {v}")


def kv_table(title: str, rows: list[tuple[str, Any]]) -> None:
    t = Table(title=title)
    t.add_column("Key")
    t.add_column("Value", overflow="fold")
    for k, v in rows:
        t.add_row(k, str(v))
    console.print(t)
