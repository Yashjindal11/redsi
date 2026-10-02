import type { Cell, RunDetail } from "../api";
import { Bar, pct } from "../ui";

function CellTable({ title, rows, linkCategory, runId }: { title: string; rows: [string, Cell][]; linkCategory?: boolean; runId: string }) {
  if (rows.length === 0) return null;
  return (
    <>
      <h2>{title}</h2>
      <table>
        <thead>
          <tr>
            <th>{title.split(" ")[0]}</th>
            <th>Executed</th>
            <th>Failed</th>
            <th>Uncertain</th>
            <th>Skipped</th>
            <th style={{ width: "35%" }} />
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, c]) => (
            <tr key={k}>
              <td>{linkCategory ? <a href={`#/runs/${runId}/tests?category=${encodeURIComponent(k)}`}>{k}</a> : k}</td>
              <td>{c.executed}</td>
              <td>{c.failed}</td>
              <td>{c.uncertain}</td>
              <td>{c.skipped}</td>
              <td>
                <Bar
                  parts={[
                    { value: c.passed, tone: "good", label: "pass" },
                    { value: c.failed, tone: "bad", label: "fail" },
                    { value: c.uncertain, tone: "warn", label: "uncertain" },
                    { value: c.skipped, tone: "idle", label: "skipped" },
                  ]}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function CoveragePage({ run }: { run: RunDetail }) {
  const cov = run.coverage;
  return (
    <>
      <p className="note">{cov.disclaimer}</p>
      <div className="cards">
        <div className="card">
          <span className="muted">Taxonomy categories exercised</span>
          <b>{pct(cov.taxonomy_fraction, 0)}</b>
        </div>
        {cov.requirements_total !== null && (
          <div className="card">
            <span className="muted">Spec requirements exercised</span>
            <b>
              {Object.values(cov.requirements).filter((c) => c.executed).length} / {cov.requirements_total}
            </b>
          </div>
        )}
      </div>
      <h2>Domains</h2>
      <table>
        <tbody>
          {Object.entries(cov.domains).map(([d, v]) => (
            <tr key={d}>
              <td>{d}</td>
              <td>
                {v.categories_tested} / {v.categories_total} categories
              </td>
              <td style={{ width: "50%" }}>
                <Bar
                  parts={[
                    { value: v.categories_tested, tone: "good", label: "tested" },
                    { value: v.categories_total - v.categories_tested, tone: "idle", label: "untested" },
                  ]}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <CellTable title="Categories" rows={Object.entries(cov.categories)} linkCategory runId={run.run_id} />
      <CellTable title="Strategies (mutation)" rows={Object.entries(cov.strategies)} runId={run.run_id} />
      <CellTable title="Requirements" rows={Object.entries(cov.requirements)} runId={run.run_id} />
      <h2>Input space</h2>
      <table>
        <tbody>
          <tr>
            <td>Capabilities exercised</td>
            <td>{Object.entries(cov.capabilities).map(([k, v]) => `${k}: ${v}`).join(" · ") || "-"}</td>
          </tr>
          <tr>
            <td>Input lengths (chars)</td>
            <td>{Object.entries(cov.input_lengths).map(([k, v]) => `${k}: ${v}`).join(" · ") || "-"}</td>
          </tr>
          <tr>
            <td>Tools called by target</td>
            <td>{Object.entries(cov.tools_called).map(([k, v]) => `${k}: ${v}`).join(" · ") || "-"}</td>
          </tr>
        </tbody>
      </table>
    </>
  );
}
