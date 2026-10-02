import { api } from "./api";
import { RunsPage } from "./pages/Runs";
import { OverviewPage } from "./pages/Overview";
import { CoveragePage } from "./pages/Coverage";
import { FindingsPage } from "./pages/Findings";
import { FindingPage } from "./pages/Finding";
import { TestsPage } from "./pages/Tests";
import { ComparePage } from "./pages/Compare";
import { LivePage } from "./pages/Live";
import { Loading, useAsync, useHashRoute } from "./ui";

const RUN_TABS: [string, string][] = [
  ["", "Overview"],
  ["coverage", "Coverage"],
  ["findings", "Findings"],
  ["tests", "Test explorer"],
  ["live", "Campaign"],
];

function RunShell({ runId, tab, sub }: { runId: string; tab: string; sub?: string }) {
  const run = useAsync(() => api.run(runId), [runId]);
  return (
    <Loading state={run}>
      {run.data && (
        <>
          <div className="runhead">
            <h1>{run.data.name ?? run.data.run_id}</h1>
            <span className="muted">
              {run.data.target.name} · {run.data.run_id}
            </span>
          </div>
          <nav className="tabs">
            {RUN_TABS.map(([key, label]) => (
              <a key={key} href={`#/runs/${run.data!.run_id}${key ? `/${key}` : ""}`} className={tab === key ? "active" : ""}>
                {label}
              </a>
            ))}
          </nav>
          {tab === "" && <OverviewPage run={run.data} />}
          {tab === "coverage" && <CoveragePage run={run.data} />}
          {tab === "findings" && !sub && <FindingsPage runId={run.data.run_id} />}
          {tab === "findings" && sub && <FindingPage runId={run.data.run_id} findingId={sub} />}
          {tab === "tests" && <TestsPage runId={run.data.run_id} />}
          {tab === "live" && <LivePage runId={run.data.run_id} />}
        </>
      )}
    </Loading>
  );
}

export function App() {
  const [section, id, tab = "", sub] = useHashRoute();
  return (
    <>
      <header>
        <a href="#/" className="brand">
          Red<span>SI</span>
        </a>
        <nav>
          <a href="#/">Runs</a>
          <a href="#/compare">Regression</a>
          <a href="/api/docs" target="_blank" rel="noreferrer">
            API
          </a>
        </nav>
      </header>
      <main>
        {(!section || section === "runs") && !id && <RunsPage />}
        {section === "runs" && id && <RunShell runId={id} tab={tab} sub={sub} />}
        {section === "compare" && <ComparePage />}
      </main>
      <footer className="muted">
        Evaluation results describe the tests that were run. They are not evidence that a system is safe.
      </footer>
    </>
  );
}
