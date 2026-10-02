import { useState } from "react";
import { api } from "../api";
import { Loading, VerdictTag, hashParams, useAsync } from "../ui";

const PAGE = 100;

export function TestsPage({ runId }: { runId: string }) {
  const initial = hashParams();
  const [category, setCategory] = useState(initial.get("category") ?? "");
  const [verdict, setVerdict] = useState("");
  const [strategy, setStrategy] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const tests = useAsync(
    () => api.tests(runId, { category, verdict, strategy, q, offset: String(offset), limit: String(PAGE) }),
    [runId, category, verdict, strategy, q, offset],
  );
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    setOffset(0);
    set(v);
  };
  return (
    <>
      <div className="filters">
        <input placeholder="category prefix" value={category} onChange={(e) => reset(setCategory)(e.target.value)} />
        <select value={verdict} onChange={(e) => reset(setVerdict)(e.target.value)}>
          <option value="">any verdict</option>
          {["pass", "fail", "uncertain", "error", "skip"].map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
        <input placeholder="mutation strategy" value={strategy} onChange={(e) => reset(setStrategy)(e.target.value)} />
        <input placeholder="search prompt" value={q} onChange={(e) => reset(setQ)(e.target.value)} />
      </div>
      <Loading state={tests}>
        <p className="muted">{tests.data?.total ?? 0} tests</p>
        <table>
          <thead>
            <tr>
              <th>Test</th>
              <th>Verdict</th>
              <th>Category</th>
              <th>Prompt</th>
              <th>Origin</th>
              <th>Evaluators</th>
            </tr>
          </thead>
          <tbody>
            {(tests.data?.items ?? []).map((t) => (
              <tr key={t.id}>
                <td>
                  <code>{t.id}</code>
                </td>
                <td>
                  <VerdictTag v={t.verdict} />
                  {t.skipped_reason && <div className="muted small">{t.skipped_reason}</div>}
                </td>
                <td>{t.category}</td>
                <td className="prompt">{t.prompt}</td>
                <td className="small">
                  {t.strategies.length ? t.strategies.join(" → ") : t.generator}
                  {t.parent && <div className="muted">from {t.parent}</div>}
                </td>
                <td className="small">{t.evaluators.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="pager">
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            ← prev
          </button>
          <button disabled={!tests.data || offset + PAGE >= tests.data.total} onClick={() => setOffset(offset + PAGE)}>
            next →
          </button>
        </div>
      </Loading>
    </>
  );
}
