"""Read-only HTTP API over the run store, plus the dashboard's static files.

Run with ``redsi serve`` (requires ``pip install 'redsi[web]'``). Binds to
127.0.0.1 by default. The API never executes targets or user code; it only
reads artifacts from the store directory.
"""

from __future__ import annotations

import asyncio
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from redsi._version import __version__
from redsi.campaign.artifact import RunArtifact
from redsi.regression import compare
from redsi.store import RunStore, load_artifact

_RUN_ID = re.compile(r"^(latest|RUN-[A-Za-z0-9-]{1,64})$")
STATIC_DIR = Path(__file__).parent / "static"


@lru_cache(maxsize=32)
def _cached(path: str, mtime: float) -> RunArtifact:
    return load_artifact(path)


def create_app(store_dir: str | Path = ".redsi") -> FastAPI:
    store = RunStore(store_dir)
    app = FastAPI(
        title="RedSI", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )

    def load(run_id: str) -> RunArtifact:
        if not _RUN_ID.match(run_id):
            raise HTTPException(400, "invalid run id")
        try:
            path = store.resolve(run_id)
        except FileNotFoundError:
            raise HTTPException(404, f"run {run_id} not found") from None
        if path.resolve().parent != store.runs_dir.resolve():
            raise HTTPException(400, "invalid run id")
        return _cached(str(path), path.stat().st_mtime)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "store": str(store.root)}

    @app.get("/api/runs")
    def runs() -> list[dict[str, Any]]:
        return store.runs()

    @app.get("/api/runs/{run_id}")
    def run(run_id: str) -> dict[str, Any]:
        art = load(run_id)
        data = art.model_dump(mode="json", exclude={"cases", "findings"})
        data["finding_count"] = len(art.findings)
        data["total_cost_usd"] = art.metrics.total_cost_usd
        data["pass_rate_by_domain"] = _domain_rates(art)
        return data

    @app.get("/api/runs/{run_id}/findings")
    def findings(
        run_id: str,
        severity: Annotated[list[str] | None, Query()] = None,
        status: Annotated[list[str] | None, Query()] = None,
        category: str | None = None,
        reproducible: bool | None = None,
        q: str | None = None,
    ) -> list[dict[str, Any]]:
        art = load(run_id)
        out = []
        for f in art.findings:
            if severity and f.severity.value not in severity:
                continue
            if status and f.status.value not in status:
                continue
            if category and not f.category.startswith(category):
                continue
            rep = f.reproducibility
            if reproducible is not None:
                was = bool(rep and rep.attempts and rep.failures)
                if was != reproducible:
                    continue
            if q and q.lower() not in (f.title + f.explanation).lower():
                continue
            out.append(
                {
                    "id": f.id,
                    "title": f.title,
                    "category": f.category,
                    "severity": f.severity.value,
                    "status": f.status.value,
                    "confidence": f.confidence,
                    "explanation": f.explanation,
                    "reproducibility": rep.model_dump(mode="json") if rep else None,
                    "strategies": f.origin.strategies if f.origin else [],
                    "created_at": f.created_at.isoformat(),
                }
            )
        return out

    @app.get("/api/runs/{run_id}/findings/{finding_id}")
    def finding(run_id: str, finding_id: str) -> dict[str, Any]:
        art = load(run_id)
        try:
            f = art.finding(finding_id)
        except KeyError:
            raise HTTPException(404, "finding not found") from None
        record = art.record(f.case_id)
        history = []
        for summary in store.runs():
            other = load(summary["run_id"])
            match = next((x for x in other.findings if x.fingerprint == f.fingerprint), None)
            try:
                verdict = other.record(f.case_id).verdict.value
            except KeyError:
                verdict = None
            if match or verdict:
                history.append(
                    {
                        "run_id": other.run_id,
                        "created_at": other.created_at.isoformat(),
                        "verdict": verdict,
                        "finding": match.id if match else None,
                        "status": match.status.value if match else None,
                    }
                )
        return {
            "finding": f.model_dump(mode="json"),
            "record": record.model_dump(mode="json"),
            "reproduce": f"redsi reproduce {f.id} --run {art.run_id}",
            "history": history,
        }

    @app.get("/api/runs/{run_id}/tests")
    def tests(
        run_id: str,
        category: str | None = None,
        verdict: str | None = None,
        strategy: str | None = None,
        q: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        art = load(run_id)
        rows = []
        for r in art.cases:
            c = r.case
            chain = c.origin.strategies if c.origin else []
            if category and not c.category.startswith(category):
                continue
            if verdict and r.verdict.value != verdict:
                continue
            if strategy and strategy not in chain:
                continue
            if q and q.lower() not in c.input.prompt.lower():
                continue
            rows.append(
                {
                    "id": c.id,
                    "category": c.category,
                    "prompt": c.input.prompt[:300],
                    "verdict": r.verdict.value,
                    "confidence": r.assessment.confidence,
                    "strategies": chain,
                    "parent": c.relation.case_id if c.relation else None,
                    "generator": c.origin.generator if c.origin else (c.suite or "suite"),
                    "evaluators": [e.type for e in c.evaluators],
                    "skipped_reason": r.skipped_reason,
                }
            )
        return {"total": len(rows), "items": rows[offset : offset + limit]}

    @app.get("/api/runs/{run_id}/tests/{case_id}")
    def test_detail(run_id: str, case_id: str) -> dict[str, Any]:
        try:
            return load(run_id).record(case_id).model_dump(mode="json")
        except KeyError:
            raise HTTPException(404, "test not found") from None

    @app.get("/api/compare")
    def compare_runs(baseline: str, candidate: str) -> dict[str, Any]:
        cmp = compare(load(baseline), load(candidate))
        return cmp.model_dump(mode="json") | {"pass_rate_delta": cmp.pass_rate_delta}

    @app.get("/api/runs/{run_id}/events")
    def events(
        run_id: str, limit: int = Query(default=500, ge=1, le=10000)
    ) -> list[dict[str, Any]]:
        path = _events_path(store, run_id)
        if not path.is_file():
            return []
        lines = path.read_text("utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]

    @app.websocket("/api/runs/{run_id}/events/ws")
    async def events_ws(ws: WebSocket, run_id: str) -> None:
        """Stream a run's event log as it is written (live campaign progress)."""
        await ws.accept()
        path = _events_path(store, run_id)
        position = 0
        try:
            while True:
                if path.is_file():
                    with path.open("r", encoding="utf-8") as fh:
                        fh.seek(position)
                        chunk = fh.read()
                        position = fh.tell()
                    for line in chunk.splitlines():
                        if line.strip():
                            await ws.send_text(line)
                            if '"campaign.finished"' in line:
                                await ws.close()
                                return
                await asyncio.sleep(0.5)
        except WebSocketDisconnect:
            return

    if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        def no_ui() -> JSONResponse:
            return JSONResponse(
                {
                    "message": "Dashboard assets not built. Run `npm --prefix web/frontend run build` or use the API at /api/docs."
                }
            )

    return app


def _events_path(store: RunStore, run_id: str) -> Path:
    if not _RUN_ID.match(run_id) or run_id == "latest":
        raise HTTPException(400, "invalid run id")
    return store.events_path(run_id)


def _domain_rates(art: RunArtifact) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for cat, cell in art.coverage.categories.items():
        d = out.setdefault(
            cat.split(".", 1)[0], {"executed": 0, "passed": 0, "failed": 0, "uncertain": 0}
        )
        d["executed"] += cell.executed
        d["passed"] += cell.passed
        d["failed"] += cell.failed
        d["uncertain"] += cell.uncertain
    return out
