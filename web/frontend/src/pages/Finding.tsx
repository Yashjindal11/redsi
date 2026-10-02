import { api } from "../api";
import { Loading, Sev, VerdictTag, useAsync, when } from "../ui";

export function FindingPage({ runId, findingId }: { runId: string; findingId: string }) {
  const detail = useAsync(() => api.finding(runId, findingId), [runId, findingId]);
  return (
    <Loading state={detail}>
      {detail.data &&
        (() => {
          const { finding: f, record, reproduce, history } = detail.data;
          return (
            <div className="finding">
              <a href={`#/runs/${runId}/findings`}>← all findings</a>
              <h2>
                {f.id} <Sev s={f.severity} /> <span className="muted">{f.status}</span>
              </h2>
              <p>
                <code>{f.category}</code> · confidence {f.confidence.toFixed(2)} · test <code>{f.case_id}</code>
                {f.origin?.strategies.length ? <> · mutations {f.origin.strategies.join(" → ")}</> : null}
                {f.requirements.length ? <> · requirements {f.requirements.join(", ")}</> : null}
              </p>

              <div className="split">
                <section>
                  <h3>Input</h3>
                  <pre>{f.input.prompt}</pre>
                  {f.input.system && (
                    <>
                      <h4>System</h4>
                      <pre>{f.input.system}</pre>
                    </>
                  )}
                  {f.input.history.length > 0 && (
                    <>
                      <h4>History</h4>
                      <pre>{f.input.history.map((m) => `[${m.role}] ${m.content}`).join("\n")}</pre>
                    </>
                  )}
                  {f.input.context.length > 0 && (
                    <>
                      <h4>Context documents</h4>
                      {f.input.context.map((d, i) => (
                        <pre key={i}>
                          [{d.id ?? i + 1}] {d.content}
                        </pre>
                      ))}
                    </>
                  )}
                </section>
                <section>
                  <h3>Observed output</h3>
                  <pre>{f.output.text || f.output.error}</pre>
                  {f.output.tool_calls.length > 0 && (
                    <>
                      <h4>Tool calls</h4>
                      <pre>{f.output.tool_calls.map((c) => `${c.name}(${JSON.stringify(c.arguments)})${c.error ? ` -> error: ${c.error}` : ""}`).join("\n")}</pre>
                    </>
                  )}
                  {record.outputs.length > 1 && (
                    <>
                      <h4>All samples</h4>
                      {record.outputs.map((o, i) => (
                        <pre key={i}>
                          #{i}: {o.text || o.error}
                        </pre>
                      ))}
                    </>
                  )}
                  <h4>Expected behaviour</h4>
                  <p>{f.expected ?? "-"}</p>
                </section>
              </div>

              <h3>Why it failed (observed)</h3>
              <p>{f.explanation}</p>
              <table>
                <thead>
                  <tr>
                    <th>Evaluator</th>
                    <th>Verdict</th>
                    <th>Confidence</th>
                    <th>Type</th>
                    <th>Explanation</th>
                  </tr>
                </thead>
                <tbody>
                  {f.results.map((r, i) => (
                    <tr key={i}>
                      <td>{r.evaluator}</td>
                      <td>
                        <VerdictTag v={r.verdict} />
                      </td>
                      <td>{r.confidence.toFixed(2)}</td>
                      <td>{r.deterministic ? "deterministic" : "judgement"}</td>
                      <td>
                        {r.explanation || r.error}
                        {r.evidence.length > 0 && <div className="muted small">evidence: {r.evidence.join(" | ")}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted">
                Assessment: {record.assessment.verdict} · agreement {record.assessment.agreement ?? "n/a"}
                {record.assessment.disagreement && " · evaluators disagreed"}
              </p>

              <h3>
                Inferred root cause <span className="muted small">(hypotheses, not observed facts)</span>
              </h3>
              <ul>
                {f.hypotheses.map((h, i) => (
                  <li key={i}>
                    <code>{h.cause}</code> ({h.likelihood}) {h.evidence.join("; ")}
                  </li>
                ))}
              </ul>

              <h3>Reproduction</h3>
              <pre>{reproduce}</pre>
              {f.reproducibility?.attempts ? (
                <p>
                  Reproduced in {f.reproducibility.failures}/{f.reproducibility.attempts} attempts
                  {f.reproducibility.flaky ? " (flaky)" : ""}.
                </p>
              ) : (
                <p className="muted">Not re-run yet.</p>
              )}

              <h3>History across runs</h3>
              <table>
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>When</th>
                    <th>Verdict</th>
                    <th>Finding</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.run_id}>
                      <td>
                        <a href={`#/runs/${h.run_id}`}>{h.run_id}</a>
                      </td>
                      <td>{when(h.created_at)}</td>
                      <td>
                        <VerdictTag v={h.verdict} />
                      </td>
                      <td>{h.finding ? `${h.finding} (${h.status})` : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {f.notes.length > 0 && (
                <>
                  <h3>Notes</h3>
                  <ul>
                    {f.notes.map((n, i) => (
                      <li key={i}>{n}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          );
        })()}
    </Loading>
  );
}
