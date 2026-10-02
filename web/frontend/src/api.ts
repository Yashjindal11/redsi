// Typed client for the read-only RedSI API (src/redsi/server/app.py).

export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type Verdict = "pass" | "fail" | "uncertain" | "error" | "skip";

export interface RunSummary {
  run_id: string;
  name: string | null;
  created_at: string;
  target: string;
  tests: number;
  passed: number;
  failed: number;
  pass_rate: number | null;
  findings: Partial<Record<Severity, number>>;
}

export interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number | null;
}

export interface Metrics {
  total: number;
  executed: number;
  passed: number;
  failed: number;
  uncertain: number;
  errors: number;
  skipped: number;
  pass_rate: number | null;
  findings_by_severity: Partial<Record<Severity, number>>;
  findings_by_status: Record<string, number>;
  findings_by_category: Record<string, number>;
  disagreements: number;
  target_calls: number;
  target_usage: Usage;
  evaluator_usage: Usage;
  latency_ms_mean: number | null;
  latency_ms_p50: number | null;
  latency_ms_p95: number | null;
  duration_s: number;
}

export interface Cell {
  executed: number;
  passed: number;
  failed: number;
  uncertain: number;
  errors: number;
  skipped: number;
}

export interface Coverage {
  categories: Record<string, Cell>;
  domains: Record<string, { categories_total: number; categories_tested: number }>;
  taxonomy_fraction: number;
  strategies: Record<string, Cell>;
  requirements: Record<string, Cell>;
  requirements_total: number | null;
  capabilities: Record<string, number>;
  input_lengths: Record<string, number>;
  tools_called: Record<string, number>;
  disclaimer: string;
}

export interface RunDetail {
  run_id: string;
  name: string | null;
  created_at: string;
  finished_at: string | null;
  environment: Record<string, unknown>;
  target: { kind: string; name: string; reproducible: boolean };
  models: { judges?: { model: string }[] };
  config: Record<string, unknown>;
  spec: { name: string; requirements: { id: string; kind: string; text: string }[]; unverifiable: string[] } | null;
  metrics: Metrics;
  coverage: Coverage;
  fuzz: { strategies: Record<string, { executed: number; failed: number; failure_rate: number | null }> } | null;
  stopped_reason: string | null;
  finding_count: number;
  total_cost_usd: number | null;
  pass_rate_by_domain: Record<string, { executed: number; passed: number; failed: number; uncertain: number }>;
}

export interface FindingRow {
  id: string;
  title: string;
  category: string;
  severity: Severity;
  status: string;
  confidence: number;
  explanation: string;
  reproducibility: { attempts: number; failures: number; flaky: boolean } | null;
  strategies: string[];
  created_at: string;
}

export interface EvaluationResult {
  evaluator: string;
  verdict: Verdict;
  confidence: number;
  deterministic: boolean;
  explanation: string;
  evidence: string[];
  error: string | null;
}

export interface TargetInput {
  prompt: string;
  system: string | null;
  history: { role: string; content: string }[];
  context: { id: string | null; content: string; source: string | null }[];
  tools: { name: string; description: string }[];
}

export interface TargetOutput {
  text: string;
  tool_calls: { name: string; arguments: Record<string, unknown>; error: string | null }[];
  retrieved: { id: string | null; content: string }[];
  error: string | null;
  latency_ms: number | null;
  trace: Record<string, unknown>[];
}

export interface Finding {
  id: string;
  fingerprint: string;
  case_id: string;
  category: string;
  severity: Severity;
  status: string;
  confidence: number;
  title: string;
  input: TargetInput;
  output: TargetOutput;
  expected: string | null;
  explanation: string;
  evidence: string[];
  results: EvaluationResult[];
  hypotheses: { cause: string; likelihood: string; evidence: string[]; source: string }[];
  reproducibility: { attempts: number; failures: number; flaky: boolean; checked_at: string | null } | null;
  origin: { generator: string; strategies: string[]; parent_id: string | null } | null;
  requirements: string[];
  notes: string[];
}

export interface FindingDetail {
  finding: Finding;
  record: { outputs: TargetOutput[]; assessment: { verdict: Verdict; confidence: number; agreement: number | null; disagreement: boolean; explanation: string } };
  reproduce: string;
  history: { run_id: string; created_at: string; verdict: Verdict | null; finding: string | null; status: string | null }[];
}

export interface TestRow {
  id: string;
  category: string;
  prompt: string;
  verdict: Verdict;
  confidence: number;
  strategies: string[];
  parent: string | null;
  generator: string;
  evaluators: string[];
  skipped_reason: string | null;
}

export interface CaseChange {
  case_id: string;
  category: string;
  prompt: string;
  before: Verdict | null;
  after: Verdict | null;
  severity_before: Severity | null;
  severity_after: Severity | null;
}

export interface Comparison {
  baseline_run: string;
  candidate_run: string;
  pass_rate_before: number | null;
  pass_rate_after: number | null;
  pass_rate_delta: number | null;
  shared: number;
  added: number;
  removed: number;
  regressions: CaseChange[];
  resolved: CaseChange[];
  persistent: CaseChange[];
  new_failures: CaseChange[];
  newly_uncertain: CaseChange[];
  severity_changes: CaseChange[];
  coverage_before: number;
  coverage_after: number;
  warnings: string[];
}

export interface RunEvent {
  type: string;
  ts: string;
  data: Record<string, unknown>;
}

async function get<T>(path: string, params?: Record<string, string | string[] | undefined>): Promise<T> {
  const url = new URL(path, window.location.origin);
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v === undefined || v === "") continue;
    for (const item of Array.isArray(v) ? v : [v]) url.searchParams.append(k, item);
  }
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}

export const api = {
  runs: () => get<RunSummary[]>("/api/runs"),
  run: (id: string) => get<RunDetail>(`/api/runs/${encodeURIComponent(id)}`),
  findings: (id: string, p: Record<string, string | string[] | undefined>) =>
    get<FindingRow[]>(`/api/runs/${encodeURIComponent(id)}/findings`, p),
  finding: (id: string, fid: string) =>
    get<FindingDetail>(`/api/runs/${encodeURIComponent(id)}/findings/${encodeURIComponent(fid)}`),
  tests: (id: string, p: Record<string, string | undefined>) =>
    get<{ total: number; items: TestRow[] }>(`/api/runs/${encodeURIComponent(id)}/tests`, p),
  compare: (a: string, b: string) => get<Comparison>("/api/compare", { baseline: a, candidate: b }),
  events: (id: string) => get<RunEvent[]>(`/api/runs/${encodeURIComponent(id)}/events`, { limit: "10000" }),
  eventsSocket: (id: string) => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return new WebSocket(`${proto}://${window.location.host}/api/runs/${encodeURIComponent(id)}/events/ws`);
  },
};
