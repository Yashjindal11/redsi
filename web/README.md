# RedSI web dashboard

A read-only React + TypeScript dashboard over the run store. The API lives in
the Python package (`src/redsi/server`); this directory is only the UI.

```bash
pip install -e ".[web]"          # FastAPI + uvicorn
cd web/frontend && npm install

# Production-style: build into the Python package, then serve both from one port
npm run build                    # writes src/redsi/server/static/
redsi serve                      # http://127.0.0.1:8765

# Development: hot reload, API proxied to a running `redsi serve`
redsi serve &                    # API on :8765
npm run dev                      # UI on :5173
```

Pages: runs (with date filter), run overview, coverage, findings (filter by
severity, status, category, reproducibility, text), finding detail (input,
output, expected behaviour, evaluator votes, evidence, root-cause hypotheses,
reproduction command, history across runs), test explorer, regression
comparison, and a campaign view that follows a running campaign live over a
WebSocket.

Security: the server binds to `127.0.0.1`, has no authentication, never runs
targets, and only reads artifacts from the store directory. Do not expose it
publicly without putting authentication in front of it.
