"""Self-contained HTML report (no external assets, everything escaped)."""

from __future__ import annotations

import json
from html import escape

from redsi.campaign.artifact import RunArtifact
from redsi.core.models import Finding
from redsi.regression import Comparison
from redsi.reporting.common import (
    SEVERITY_ORDER,
    executive_summary,
    failure_distribution,
    fmt_usd,
    recommendations,
    reproduction_command,
)

_CSS = """
body{font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;color:#1d2330;background:#f6f7f9}
main{max-width:1100px;margin:0 auto;padding:24px}
h1{font-size:22px}h2{font-size:17px;margin-top:32px;border-bottom:1px solid #dde1e7;padding-bottom:4px}
table{border-collapse:collapse;width:100%;background:#fff;margin:8px 0}
td,th{border:1px solid #e3e6eb;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f0f2f5}pre{background:#0f1720;color:#e6edf3;padding:10px;border-radius:6px;white-space:pre-wrap;word-break:break-word;max-height:360px;overflow:auto}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.card{background:#fff;border:1px solid #e3e6eb;border-radius:8px;padding:10px}.card b{display:block;font-size:20px}
.sev{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600;color:#fff}
.critical{background:#8b1e3f}.high{background:#c2410c}.medium{background:#b45309}.low{background:#2563eb}.info{background:#64748b}
details{background:#fff;border:1px solid #e3e6eb;border-radius:8px;margin:8px 0;padding:8px 12px}
summary{cursor:pointer;font-weight:600}.muted{color:#64748b}.note{background:#fff7e6;border-left:3px solid #b45309;padding:8px 12px}
"""


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _sev(s: str) -> str:
    return f'<span class="sev {_e(s)}">{_e(s)}</span>'


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _finding(art: RunArtifact, f: Finding) -> str:
    rows = [
        ["Category", f"<code>{_e(f.category)}</code>"],
        ["Severity", _sev(f.severity.value)],
        ["Status", f"{_e(f.status.value)} (confidence {f.confidence:.2f})"],
        ["Evaluators", _e(", ".join(f.evaluators) or "-")],
    ]
    if f.reproducibility and f.reproducibility.attempts:
        r = f.reproducibility
        rows.append(
            [
                "Reproducibility",
                _e(f"{r.failures}/{r.attempts} failed" + (" (flaky)" if r.flaky else "")),
            ]
        )
    if f.origin and f.origin.strategies:
        rows.append(["Mutation chain", _e(" -> ".join(f.origin.strategies))])
    if f.requirements:
        rows.append(["Requirements", _e(", ".join(f.requirements))])
    parts = [
        _table(["Field", "Value"], rows),
        "<h4>Input</h4>",
        f"<pre>{_e(f.input.prompt[:4000])}</pre>",
    ]
    if f.input.system:
        parts += ["<h4>System instructions</h4>", f"<pre>{_e(f.input.system[:2000])}</pre>"]
    if f.input.context:
        parts += [
            "<h4>Context</h4>",
            "<ul>"
            + "".join(
                f"<li><code>{_e(d.id or i + 1)}</code> {_e(d.content[:300])}</li>"
                for i, d in enumerate(f.input.context)
            )
            + "</ul>",
        ]
    parts += [
        "<h4>Observed output</h4>",
        f"<pre>{_e((f.output.text or f.output.error or '')[:4000])}</pre>",
    ]
    if f.output.tool_calls:
        calls = "\n".join(f"{c.name}({json.dumps(c.arguments)})" for c in f.output.tool_calls)
        parts += ["<h4>Tool calls</h4>", f"<pre>{_e(calls)}</pre>"]
    parts += [
        f"<p><b>Expected behaviour:</b> {_e(f.expected or '-')}</p>",
        f"<p><b>Why it failed (observed):</b> {_e(f.explanation)}</p>",
    ]
    if f.evidence:
        parts.append(
            "<p><b>Evidence</b></p><ul>"
            + "".join(f"<li>{_e(e[:400])}</li>" for e in f.evidence)
            + "</ul>"
        )
    hyps = [h for h in f.hypotheses if h.cause.value != "unknown"]
    hyp_html = (
        "".join(
            f"<li><code>{_e(h.cause.value)}</code> ({_e(h.likelihood)}): {_e('; '.join(h.evidence))}</li>"
            for h in hyps
        )
        or "<li>unknown</li>"
    )
    parts += [
        f"<p><b>Inferred root cause</b> <span class='muted'>(hypothesis, not observed fact)</span></p><ul>{hyp_html}</ul>"
    ]
    parts.append(f"<p><b>Reproduce:</b> <code>{_e(reproduction_command(art, f))}</code></p>")
    return f"<details><summary>{_sev(f.severity.value)} {_e(f.id)} - {_e(f.title)}</summary>{''.join(parts)}</details>"


def render_html(
    art: RunArtifact, comparison: Comparison | None = None, max_findings: int = 200
) -> str:
    m = art.metrics
    cov = art.coverage
    sev = m.findings_by_severity
    cards = [
        ("Tests", m.total),
        ("Passed", m.passed),
        ("Failed", m.failed),
        ("Uncertain", m.uncertain),
        ("Pass rate", "-" if m.pass_rate is None else f"{m.pass_rate:.1%}"),
        ("Critical", sev.get("critical", 0)),
        ("High", sev.get("high", 0)),
        ("Coverage", f"{cov.taxonomy_fraction:.0%}"),
    ]
    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>RedSI report {_e(art.run_id)}</title><style>{_CSS}</style></head><body><main>",
        f"<h1>RedSI report - {_e(art.name or art.run_id)}</h1>",
        "<div class='cards'>"
        + "".join(
            f"<div class='card'><span class='muted'>{_e(k)}</span><b>{_e(v)}</b></div>"
            for k, v in cards
        )
        + "</div>",
        "<h2>Executive summary</h2><ul>"
        + "".join(f"<li>{_e(s)}</li>" for s in executive_summary(art))
        + "</ul>",
        "<h2>Target</h2>",
        _table(
            ["Field", "Value"],
            [
                ["Name", _e(art.target.name)],
                ["Kind", _e(art.target.kind)],
                ["Rebuildable", "yes" if art.target.reproducible else "no"],
            ],
        ),
        "<h2>Evaluation configuration</h2>",
        _table(
            ["Field", "Value"],
            [
                ["Run", _e(f"{art.run_id} ({art.created_at:%Y-%m-%d %H:%M UTC})")],
                [
                    "RedSI / Python",
                    _e(f"{art.environment.get('redsi')} / {art.environment.get('python')}"),
                ],
                ["Mode / seed", _e(f"{art.config.get('mode')} / {art.config.get('seed')}")],
                ["Suites", _e(", ".join(art.config.get("suites") or []) or "-")],
                [
                    "Judges",
                    _e(", ".join(j["model"] for j in art.models.get("judges", [])) or "none"),
                ],
            ],
        ),
        "<h2>Test coverage</h2>",
        f"<p class='note'>{_e(cov.disclaimer)}</p>",
        _table(
            ["Domain", "Categories tested"],
            [
                [_e(d), f"{v['categories_tested']}/{v['categories_total']}"]
                for d, v in cov.domains.items()
            ],
        ),
    ]
    if cov.requirement_fraction is not None:
        out.append(
            _table(
                ["Requirement", "Executed", "Failed", "Uncertain"],
                [
                    [_e(r), str(c.executed), str(c.failed), str(c.uncertain)]
                    for r, c in cov.requirements.items()
                ],
            )
        )
    if cov.strategies and set(cov.strategies) != {"(none)"}:
        out.append(
            _table(
                ["Mutation strategy", "Executed", "Failed"],
                [[_e(s), str(c.executed), str(c.failed)] for s, c in cov.strategies.items()],
            )
        )
    out += [
        "<h2>Overall results</h2>",
        _table(
            ["Metric", "Value"],
            [
                [
                    "Passed / failed / uncertain / errors / skipped",
                    _e(f"{m.passed} / {m.failed} / {m.uncertain} / {m.errors} / {m.skipped}"),
                ],
                ["Evaluator disagreements", _e(m.disagreements)],
                [
                    "Latency p50 / p95",
                    _e(f"{m.latency_ms_p50 or '-'} ms / {m.latency_ms_p95 or '-'} ms"),
                ],
                [
                    "Target tokens / cost",
                    _e(f"{m.target_usage.total_tokens} / {fmt_usd(m.target_usage.cost_usd)}"),
                ],
                [
                    "Evaluator tokens / cost",
                    _e(f"{m.evaluator_usage.total_tokens} / {fmt_usd(m.evaluator_usage.cost_usd)}"),
                ],
                ["Duration", _e(f"{m.duration_s:.1f} s")],
            ],
        ),
        "<h2>Failure distribution</h2>",
        _table(
            ["Category", "Executed", "Failed", "Uncertain", "Failure rate"],
            [
                [
                    f"<code>{_e(r['category'])}</code>",
                    str(r["executed"]),
                    str(r["failed"]),
                    str(r["uncertain"]),
                    f"{r['rate']:.0%}",
                ]
                for r in failure_distribution(art)
            ],
        ),
        "<h2>Critical findings</h2>",
    ]
    crit = [
        f
        for f in art.findings
        if f.severity.value == "critical" and f.status.value != "false_positive"
    ]
    out.append(
        "<ul>"
        + "".join(
            f"<li><b>{_e(f.id)}</b> <code>{_e(f.category)}</code> ({_e(f.status.value)}): {_e(f.title)}</li>"
            for f in crit
        )
        + "</ul>"
        if crit
        else "<p>None.</p>"
    )
    out.append("<h2>Detailed findings</h2>")
    ordered = sorted(art.findings, key=lambda f: SEVERITY_ORDER.index(f.severity))
    out += [_finding(art, f) for f in ordered[:max_findings]] or ["<p>No findings.</p>"]
    if len(art.findings) > max_findings:
        out.append(
            f"<p class='muted'>{len(art.findings) - max_findings} more findings in the JSON artifact.</p>"
        )
    out += [
        "<h2>Reproduction instructions</h2>",
        f"<pre>redsi inspect {_e(art.run_id)}\nredsi reproduce FINDING-001 --run {_e(art.run_id)} --attempts 5</pre>",
        "<h2>Regression analysis</h2>",
    ]
    if comparison is None:
        out.append("<p>No baseline supplied.</p>")
    else:
        c = comparison
        delta = c.pass_rate_delta
        out.append(
            _table(
                ["", "Count"],
                [
                    ["Shared tests", str(c.shared)],
                    ["Regressions (pass -> fail)", str(len(c.regressions))],
                    ["Resolved (fail -> pass)", str(len(c.resolved))],
                    ["Persistent failures", str(len(c.persistent))],
                    ["New failures", str(len(c.new_failures))],
                    ["Pass-rate change", "-" if delta is None else f"{delta:+.1%}"],
                ],
            )
        )
        out += [f"<p class='note'>{_e(w)}</p>" for w in c.warnings]
    recs = recommendations(art)
    out += [
        "<h2>Recommendations</h2><p class='muted'>Generic guidance by failure category; adapt to your system.</p>"
    ]
    out.append(
        "<ul>"
        + "".join(f"<li><code>{_e(cat)}</code> ({n}): {_e(g)}</li>" for cat, g, n in recs)
        + "</ul>"
        if recs
        else "<p>No confirmed or likely findings.</p>"
    )
    out += [
        "<h2>Raw artifacts</h2>",
        f"<ul><li><code>.redsi/runs/{_e(art.run_id)}.json</code></li><li><code>.redsi/runs/{_e(art.run_id)}.events.jsonl</code></li></ul>",
        "</main></body></html>",
    ]
    return "\n".join(out)
