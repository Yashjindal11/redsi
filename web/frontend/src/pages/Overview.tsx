import type { RunDetail } from "../api";
import { Bar, Card, ms, pct, usd } from "../ui";

export function OverviewPage({ run }: { run: RunDetail }) {
  const m = run.metrics;
  const sev = m.findings_by_severity;
  return (
    <>
      <div className="cards">
        <Card label="Tests" value={m.total} />
        <Card label="Passed" value={m.passed} tone="good" />
        <Card label="Failed" value={m.failed} tone="bad" />
        <Card label="Uncertain" value={m.uncertain} tone="warn" />
        <Card label="Critical" value={sev.critical ?? 0} tone={sev.critical ? "bad" : ""} />
        <Card label="High" value={sev.high ?? 0} />
        <Card label="Coverage" value={pct(run.coverage.taxonomy_fraction, 0)} />
        <Card label="Cost" value={usd(run.total_cost_usd)} />
        <Card label="Latency p50 / p95" value={`${ms(m.latency_ms_p50)} / ${ms(m.latency_ms_p95)}`} />
        <Card label="Pass rate" value={pct(m.pass_rate)} />
      </div>
      {run.stopped_reason && <p className="note">Stopped early: {run.stopped_reason}</p>}
      {run.spec && run.spec.unverifiable.length > 0 && (
        <p className="note">
          {run.spec.unverifiable.length} requirement(s) had no deterministic check and no judge model, so they could not be verified:{" "}
          {run.spec.unverifiable.join(", ")}
        </p>
      )}
      <h2>Results by domain</h2>
      <table>
        <thead>
          <tr>
            <th>Domain</th>
            <th>Executed</th>
            <th style={{ width: "50%" }}>pass / fail / uncertain</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(run.pass_rate_by_domain).map(([d, c]) => (
            <tr key={d}>
              <td>{d}</td>
              <td>{c.executed}</td>
              <td>
                <Bar
                  parts={[
                    { value: c.passed, tone: "good", label: "pass" },
                    { value: c.failed, tone: "bad", label: "fail" },
                    { value: c.uncertain, tone: "warn", label: "uncertain" },
                  ]}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2>Campaign</h2>
      <table>
        <tbody>
          <tr>
            <td>Mode / seed</td>
            <td>
              {String(run.config.mode)} / {String(run.config.seed)}
            </td>
          </tr>
          <tr>
            <td>Suites</td>
            <td>{((run.config.suites as string[]) ?? []).join(", ") || "-"}</td>
          </tr>
          <tr>
            <td>Judges</td>
            <td>{run.models.judges?.map((j) => j.model).join(", ") || "none (judge-only checks are skipped)"}</td>
          </tr>
          <tr>
            <td>Errors / skipped / disagreements</td>
            <td>
              {m.errors} / {m.skipped} / {m.disagreements}
            </td>
          </tr>
          <tr>
            <td>Target calls / tokens</td>
            <td>
              {m.target_calls} / {m.target_usage.prompt_tokens + m.target_usage.completion_tokens}
            </td>
          </tr>
          <tr>
            <td>Evaluator tokens / cost</td>
            <td>
              {m.evaluator_usage.prompt_tokens + m.evaluator_usage.completion_tokens} / {usd(m.evaluator_usage.cost_usd)}
            </td>
          </tr>
          <tr>
            <td>Duration</td>
            <td>{m.duration_s.toFixed(1)} s</td>
          </tr>
          <tr>
            <td>Environment</td>
            <td>
              RedSI {String(run.environment.redsi)} · Python {String(run.environment.python)}
            </td>
          </tr>
        </tbody>
      </table>
    </>
  );
}
