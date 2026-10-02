import { useState } from "react";
import { api, type Severity } from "../api";
import { Loading, Sev, useAsync } from "../ui";

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];
const STATUSES = ["confirmed", "likely", "uncertain", "false_positive"];

export function FindingsPage({ runId }: { runId: string }) {
  const [severity, setSeverity] = useState<string[]>([]);
  const [status, setStatus] = useState<string[]>(["confirmed", "likely", "uncertain"]);
  const [category, setCategory] = useState("");
  const [reproducible, setReproducible] = useState("");
  const [q, setQ] = useState("");
  const findings = useAsync(
    () => api.findings(runId, { severity, status, category, reproducible, q }),
    [runId, severity.join(), status.join(), category, reproducible, q],
  );
  const toggle = (list: string[], set: (v: string[]) => void, v: string) =>
    set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  return (
    <>
      <div className="filters">
        <fieldset>
          <legend>Severity</legend>
          {SEVERITIES.map((s) => (
            <label key={s}>
              <input type="checkbox" checked={severity.includes(s)} onChange={() => toggle(severity, setSeverity, s)} /> {s}
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend>Status</legend>
          {STATUSES.map((s) => (
            <label key={s}>
              <input type="checkbox" checked={status.includes(s)} onChange={() => toggle(status, setStatus, s)} /> {s}
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend>Reproduced</legend>
          <select value={reproducible} onChange={(e) => setReproducible(e.target.value)}>
            <option value="">any</option>
            <option value="true">reproduced</option>
            <option value="false">not reproduced / untested</option>
          </select>
        </fieldset>
        <input placeholder="category prefix, e.g. security" value={category} onChange={(e) => setCategory(e.target.value)} />
        <input placeholder="search" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <Loading state={findings}>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Severity</th>
              <th>Status</th>
              <th>Category</th>
              <th>Finding</th>
              <th>Reproduced</th>
            </tr>
          </thead>
          <tbody>
            {(findings.data ?? []).map((f) => (
              <tr key={f.id}>
                <td>
                  <a href={`#/runs/${runId}/findings/${f.id}`}>{f.id}</a>
                </td>
                <td>
                  <Sev s={f.severity} />
                </td>
                <td>
                  {f.status} <span className="muted">({f.confidence.toFixed(2)})</span>
                </td>
                <td>
                  <code>{f.category}</code>
                  {f.strategies.length > 0 && <div className="muted small">via {f.strategies.join(" → ")}</div>}
                </td>
                <td>{f.explanation.slice(0, 140)}</td>
                <td>
                  {f.reproducibility?.attempts ? `${f.reproducibility.failures}/${f.reproducibility.attempts}${f.reproducibility.flaky ? " (flaky)" : ""}` : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {findings.data?.length === 0 && <p className="muted">No findings match these filters.</p>}
      </Loading>
    </>
  );
}
