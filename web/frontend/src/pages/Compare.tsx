import { useState } from "react";
import { api, type CaseChange } from "../api";
import { Loading, VerdictTag, hashParams, pct, useAsync } from "../ui";

function Changes({ title, rows }: { title: string; rows: CaseChange[] }) {
  if (rows.length === 0) return null;
  return (
    <>
      <h3>
        {title} ({rows.length})
      </h3>
      <table>
        <thead>
          <tr>
            <th>Category</th>
            <th>Prompt</th>
            <th>Before</th>
            <th>After</th>
            <th>Severity</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.case_id}>
              <td>{c.category}</td>
              <td className="prompt">{c.prompt}</td>
              <td>
                <VerdictTag v={c.before} />
              </td>
              <td>
                <VerdictTag v={c.after} />
              </td>
              <td>
                {c.severity_before ?? "-"} → {c.severity_after ?? "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function ComparePage() {
  const runs = useAsync(() => api.runs(), []);
  const p = hashParams();
  const [a, setA] = useState(p.get("a") ?? "");
  const [b, setB] = useState(p.get("b") ?? "");
  const ready = a && b && a !== b;
  const cmp = useAsync(() => (ready ? api.compare(a, b) : Promise.resolve(undefined)), [a, b]);
  const update = (na: string, nb: string) => {
    setA(na);
    setB(nb);
    window.history.replaceState(null, "", `#/compare?a=${na}&b=${nb}`);
  };
  const options = (runs.data ?? []).map((r) => (
    <option key={r.run_id} value={r.run_id}>
      {r.name ?? r.run_id} ({r.target})
    </option>
  ));
  return (
    <>
      <h1>Regression</h1>
      <div className="filters">
        <label>
          Baseline{" "}
          <select value={a} onChange={(e) => update(e.target.value, b)}>
            <option value="">choose…</option>
            {options}
          </select>
        </label>
        <label>
          Candidate{" "}
          <select value={b} onChange={(e) => update(a, e.target.value)}>
            <option value="">choose…</option>
            {options}
          </select>
        </label>
      </div>
      {!ready && <p className="muted">Pick two different runs.</p>}
      {ready && (
        <Loading state={cmp}>
          {cmp.data && (
            <>
              {cmp.data.warnings.map((w) => (
                <p className="note" key={w}>
                  {w}
                </p>
              ))}
              <div className="cards">
                <div className="card">
                  <span className="muted">Pass rate</span>
                  <b>
                    {pct(cmp.data.pass_rate_before)} → {pct(cmp.data.pass_rate_after)}
                  </b>
                </div>
                <div className={`card ${cmp.data.regressions.length ? "bad" : ""}`}>
                  <span className="muted">Regressions</span>
                  <b>{cmp.data.regressions.length}</b>
                </div>
                <div className="card good">
                  <span className="muted">Resolved</span>
                  <b>{cmp.data.resolved.length}</b>
                </div>
                <div className="card">
                  <span className="muted">New failures</span>
                  <b>{cmp.data.new_failures.length}</b>
                </div>
                <div className="card">
                  <span className="muted">Shared / added / removed</span>
                  <b>
                    {cmp.data.shared} / {cmp.data.added} / {cmp.data.removed}
                  </b>
                </div>
                <div className="card">
                  <span className="muted">Coverage</span>
                  <b>
                    {pct(cmp.data.coverage_before, 0)} → {pct(cmp.data.coverage_after, 0)}
                  </b>
                </div>
              </div>
              <Changes title="Regressions (pass → fail)" rows={cmp.data.regressions} />
              <Changes title="New failures" rows={cmp.data.new_failures} />
              <Changes title="Resolved (fail → pass)" rows={cmp.data.resolved} />
              <Changes title="Severity changes" rows={cmp.data.severity_changes} />
              <Changes title="Newly uncertain" rows={cmp.data.newly_uncertain} />
              <Changes title="Persistent failures" rows={cmp.data.persistent} />
            </>
          )}
        </Loading>
      )}
    </>
  );
}
