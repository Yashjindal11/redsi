# CLI reference

All commands accept `--config/-c redsi.yaml` (default: `./redsi.yaml` if it
exists). Most accept `--json` for machine-readable output on stdout; progress
and logs go to stderr. Exit codes: **0** success, **1** quality gate failed,
**2** usage or configuration error.

| Command | Purpose |
|---|---|
| `redsi init [DIR]` | Create `redsi.yaml`, a toy `my_agent.py`, `system.yaml` |
| `redsi test [TARGET]` | Run a campaign; apply the gate |
| `redsi generate` | Generate tests (spec / suites + mutations) to a file, without running |
| `redsi evaluate RECORDS` | Evaluate pre-recorded `{input, output, ...}` items (e.g. logs) |
| `redsi reproduce FINDING` | Re-run a finding N times; record reproducibility |
| `redsi compare A [B]` | Regression analysis between runs; apply the gate |
| `redsi report [RUN]` | Markdown / HTML / JSON report |
| `redsi inspect [RUN or FINDING]` | Summary, or full detail of one finding |
| `redsi runs` | List stored runs |
| `redsi triage FINDING --status S` | Record a human review decision |
| `redsi suites [--categories]` | List suites, or the failure taxonomy |
| `redsi targets` | Supported target kinds |
| `redsi config [show/validate]` | Show or validate configuration |
| `redsi serve` | Read-only web dashboard (`pip install 'redsi[web]'`) |
| `redsi benchmark` | Planted-fault benchmark of discovery methods |

## `redsi test`

```bash
redsi test my_agent.py:answer                          # Python callable
redsi test https://api.example.com/chat                # HTTP endpoint
redsi test openai:gpt-4o-mini --judge anthropic:claude-3-5-haiku-latest
redsi test --suite factuality --suite robustness --mode deep
redsi test --spec system.yaml --generator ollama:llama3.1 --spec-probes 5
redsi test --tests my_tests.yaml --no-fuzz
redsi test --category "security.*" --isolate --timeout 20
redsi test --max-cost 2.50 --max-failures 50 --concurrency 16
redsi test --out baseline.json                         # save artifact copy
redsi test --baseline baseline.json --max-regressions 0 --min-pass-rate 0.9
redsi test --report report.html
```

Modes: `quick` (≤60 tests, no fuzzing), `standard` (≤400, 2 variants per
seed), `deep` (≤3000, 4 variants per seed, 3 adaptive rounds, depth 2),
`custom` (only what you set).

## Configuration file

See the template written by `redsi init`, or
[`redsi.config`](../src/redsi/config.py). HTTP targets with custom request
shapes:

```yaml
target:
  kind: http
  url: https://api.example.com/v1/chat
  body: {messages: [{role: user, content: "{{prompt}}"}], context: "{{context}}"}
  headers: {Authorization: "Bearer ${MY_API_KEY}"}   # env var, resolved at call time
  response_path: choices.0.message.content
```
