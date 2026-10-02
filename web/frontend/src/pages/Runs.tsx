import { useMemo, useState } from "react";
import { api } from "../api";
import { Loading, Sev, pct, useAsync, when } from "../ui";

export function RunsPage() {
  const runs = useAsync(() => api.runs(), []);
  const [since, setSince] = useState("");
  const rows = useMemo(
    () => (runs.data ?? []).filter((r) => !since || new Date(r.created_at) >= new Date(since)),
    [runs.data, since],
  );
  return (
    <Loading state={runs}>
      <div className="toolbar">
        <h1>Runs</h1>
        <label>
          since <input type="date" value={since} onChange={(e) => setSince(e.target.value)} />
        </label>
      </div>
      {rows.length === 0 ? (
        <p className="muted">
          No runs yet. Run <code>redsi test</code> in this project, then refresh.
        </p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Run</th>
              <th>When</th>
              <th>Target</th>
              <th>Tests</th>
              <th>Pass rate</th>
              <th>Findings</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.run_id}>
                <td>
                  <a href={`#/runs/${r.run_id}`}>{r.name ?? r.run_id}</a>
                </td>
                <td>{when(r.created_at)}</td>
                <td>{r.target}</td>
                <td>{r.tests}</td>
                <td>{pct(r.pass_rate)}</td>
                <td className="sevs">
                  {(["critical", "high", "medium", "low", "info"] as const).map((s) =>
                    r.findings[s] ? (
                      <span key={s}>
                        <Sev s={s} /> {r.findings[s]}
                      </span>
                    ) : null,
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Loading>
  );
}
