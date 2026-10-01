"""Markdown report."""

from __future__ import annotations

import json

from redsi.campaign.artifact import RunArtifact
from redsi.core.models import Finding, FindingStatus
from redsi.regression import Comparison
from redsi.reporting.common import (
    SEVERITY_ORDER,
    executive_summary,
    failure_distribution,
    fmt_usd,
    recommendations,
    reproduction_command,
)


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _fence(text: str, lang: str = "") -> str:
    fence = "````" if "```" in text else "```"
    return f"{fence}{lang}\n{text}\n{fence}"


def _finding(art: RunArtifact, f: Finding) -> list[str]:
    out = [f"### {f.id} - {_cell(f.title)}", ""]
    out += [
        "| Field | Value |",
        "|---|---|",
        f"| Category | `{f.category}` |",
        f"| Severity | **{f.severity.value}** |",
        f"| Status | {f.status.value} (confidence {f.confidence:.2f}) |",
        f"| Evaluators | {_cell(', '.join(f.evaluators) or '-')} |",
    ]
    if f.reproducibility and f.reproducibility.attempts:
        r = f.reproducibility
        out.append(
            f"| Reproducibility | {r.failures}/{r.attempts} attempts failed{' (flaky)' if r.flaky else ''} |"
        )
    if f.origin and f.origin.strategies:
        out.append(f"| Mutation chain | {_cell(' -> '.join(f.origin.strategies))} |")
    if f.requirements:
        out.append(f"| Requirements | {_cell(', '.join(f.requirements))} |")
    out += ["", "**Input**", "", _fence(f.input.prompt[:4000])]
    if f.input.system:
        out += ["", "**System instructions**", "", _fence(f.input.system[:2000])]
    if f.input.context:
        out += ["", f"**Context** ({len(f.input.context)} documents)", ""]
        out += [
            f"- `{d.id or i + 1}`: {_cell(d.content[:300])}" for i, d in enumerate(f.input.context)
        ]
    out += ["", "**Observed output**", "", _fence((f.output.text or f.output.error or "")[:4000])]
    if f.output.tool_calls:
        calls = "\n".join(f"{c.name}({json.dumps(c.arguments)})" for c in f.output.tool_calls)
        out += ["", "**Tool calls**", "", _fence(calls)]
    out += [
        "",
        f"**Expected behaviour:** {f.expected or '-'}",
        "",
        f"**Why it failed (observed):** {f.explanation}",
    ]
    if f.evidence:
        out += ["", "**Evidence**", ""] + [f"- {_cell(e[:400])}" for e in f.evidence]
    hyps = [h for h in f.hypotheses if h.cause.value != "unknown"]
    out += ["", "**Inferred root cause (hypothesis, not observed fact):** "]
    if hyps:
        out += [f"- `{h.cause.value}` ({h.likelihood}): {'; '.join(h.evidence)}" for h in hyps]
    else:
        out.append("- unknown - no trace evidence pointed to a specific cause")
    out += ["", f"**Reproduce:** `{reproduction_command(art, f)}`", ""]
    return out


def render_markdown(
    art: RunArtifact, comparison: Comparison | None = None, max_findings: int = 100
) -> str:
    m = art.metrics
    lines = [f"# RedSI report - {art.name or art.run_id}", ""]
    lines += ["## Executive summary", ""] + [f"- {s}" for s in executive_summary(art)] + [""]

    lines += ["## Target", "", f"- Name: `{art.target.name}`", f"- Kind: `{art.target.kind}`"]
    lines.append(f"- Rebuildable from artifact: {'yes' if art.target.reproducible else 'no'}")
    if art.models.get("judges"):
        lines.append(f"- Judges: {', '.join(j['model'] for j in art.models['judges'])}")
    lines.append("")

    cfg = art.config
    lines += ["## Evaluation configuration", ""]
    lines += [
        f"- Run: `{art.run_id}` ({art.created_at:%Y-%m-%d %H:%M UTC})",
        f"- RedSI {art.environment.get('redsi')}, Python {art.environment.get('python')}",
        f"- Mode: {cfg.get('mode')}; suites: {', '.join(cfg.get('suites') or []) or '-'}; seed: {cfg.get('seed')}",
        f"- Concurrency {cfg.get('concurrency')}, timeout {cfg.get('timeout')}s, retries {cfg.get('retries')}",
    ]
    if art.spec:
        lines.append(
            f"- Specification: `{art.spec.get('name')}` ({len(art.spec.get('requirements', []))} requirements)"
        )
    lines.append("")

    cov = art.coverage
    lines += ["## Test coverage", "", f"> {cov.disclaimer}", ""]
    lines.append(f"Taxonomy categories exercised: {cov.taxonomy_fraction:.0%}")
    if cov.requirement_fraction is not None:
        lines.append(f"  \nSpecification requirements exercised: {cov.requirement_fraction:.0%}")
    lines += ["", "| Domain | Categories tested |", "|---|---|"]
    lines += [
        f"| {d} | {v['categories_tested']}/{v['categories_total']} |"
        for d, v in cov.domains.items()
    ]
    if cov.strategies and set(cov.strategies) != {"(none)"}:
        lines += ["", "| Mutation strategy | Executed | Failed |", "|---|---|---|"]
        lines += [f"| {s} | {c.executed} | {c.failed} |" for s, c in cov.strategies.items()]
    lines.append("")

    lines += ["## Overall results", "", "| Metric | Value |", "|---|---|"]
    lines += [
        f"| Tests | {m.total} |",
        f"| Passed / failed / uncertain / errors / skipped | {m.passed} / {m.failed} / {m.uncertain} / {m.errors} / {m.skipped} |",
        f"| Pass rate | {'-' if m.pass_rate is None else f'{m.pass_rate:.1%}'} |",
        f"| Evaluator disagreements | {m.disagreements} |",
        f"| Target calls | {m.target_calls} |",
        f"| Latency p50 / p95 | {m.latency_ms_p50 or '-'} ms / {m.latency_ms_p95 or '-'} ms |",
        f"| Target tokens / cost | {m.target_usage.total_tokens} / {fmt_usd(m.target_usage.cost_usd)} |",
        f"| Evaluator tokens / cost | {m.evaluator_usage.total_tokens} / {fmt_usd(m.evaluator_usage.cost_usd)} |",
        f"| Duration | {m.duration_s:.1f} s |",
        "",
    ]

    lines += [
        "## Failure distribution",
        "",
        "| Category | Executed | Failed | Uncertain | Failure rate |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| `{r['category']}` | {r['executed']} | {r['failed']} | {r['uncertain']} | {r['rate']:.0%} |"
        for r in failure_distribution(art)
    ]
    lines.append("")

    critical = [
        f
        for f in art.findings
        if f.severity.value == "critical" and f.status != FindingStatus.FALSE_POSITIVE
    ]
    lines += ["## Critical findings", ""]
    lines += [
        f"- **{f.id}** `{f.category}` ({f.status.value}): {_cell(f.title)}" for f in critical
    ] or ["None."]
    lines.append("")

    lines += ["## Detailed findings", ""]
    if not art.findings:
        lines += ["No findings.", ""]
    by_sev = sorted(art.findings, key=lambda f: SEVERITY_ORDER.index(f.severity))
    for f in by_sev[:max_findings]:
        lines += _finding(art, f)
    if len(art.findings) > max_findings:
        lines += [f"_{len(art.findings) - max_findings} more findings in the JSON artifact._", ""]

    lines += [
        "## Reproduction instructions",
        "",
        "Every finding can be replayed from the run artifact:",
        "",
        _fence(
            f"redsi inspect {art.run_id}\nredsi reproduce FINDING-001 --run {art.run_id} --attempts 5",
            "bash",
        ),
    ]
    if not art.target.reproducible:
        lines.append(
            "\nThe target could not be serialised (e.g. a lambda); pass it explicitly with `--target`."
        )
    lines.append("")

    lines += ["## Regression analysis", ""]
    if comparison is None:
        lines += [
            "No baseline supplied. Use `redsi compare BASELINE CANDIDATE` or `redsi test --baseline`.",
            "",
        ]
    else:
        c = comparison
        delta = c.pass_rate_delta
        lines += [
            f"Baseline `{c.baseline_run}` -> candidate `{c.candidate_run}`",
            "",
            "| | Count |",
            "|---|---|",
            f"| Shared tests | {c.shared} |",
            f"| Regressions (pass -> fail) | {len(c.regressions)} |",
            f"| Resolved (fail -> pass) | {len(c.resolved)} |",
            f"| Persistent failures | {len(c.persistent)} |",
            f"| New failures | {len(c.new_failures)} |",
            f"| Pass-rate change | {'-' if delta is None else f'{delta:+.1%}'} |",
            "",
        ]
        lines += [f"- regression `{r.category}`: {_cell(r.prompt)}" for r in c.regressions[:50]]
        lines += [f"- warning: {w}" for w in c.warnings]
        lines.append("")

    lines += [
        "## Recommendations",
        "",
        "_Generic guidance by failure category; adapt to your system._",
        "",
    ]
    recs = recommendations(art)
    lines += [f"- `{cat}` ({n}): {g}" for cat, g, n in recs] or ["No confirmed or likely findings."]
    lines.append("")

    lines += [
        "## Raw artifacts",
        "",
        f"- Run artifact: `.redsi/runs/{art.run_id}.json`",
        f"- Event log: `.redsi/runs/{art.run_id}.events.jsonl`",
        "",
    ]
    return "\n".join(lines)
