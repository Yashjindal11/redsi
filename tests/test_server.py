import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from redsi import RedSI, Target, TestCase
from redsi.evaluators import NotContains, NumericAnswer
from redsi.server import create_app

CASES = [
    TestCase(
        input="2+2?", category="reasoning.arithmetic", reference="4", evaluators=[NumericAnswer()]
    ),
    TestCase(
        input="leak?", category="security.data_leakage", evaluators=[NotContains(texts=["CANARY"])]
    ),
]


@pytest.fixture
async def client(tmp_path):
    store = tmp_path / ".redsi"
    a = await RedSI(
        Target.from_function(lambda p: "4" if "2+2" in p else "CANARY", name="bot"), store=store
    ).run(tests=CASES, mode="custom")
    b = await RedSI(Target.from_function(lambda p: "5", name="bot"), store=store).run(
        tests=CASES, mode="custom"
    )
    return TestClient(create_app(store)), a, b


async def test_runs_and_run_detail(client) -> None:
    c, a, b = client
    runs = c.get("/api/runs").json()
    assert {r["run_id"] for r in runs} == {a.run_id, b.run_id}
    detail = c.get(f"/api/runs/{a.run_id}").json()
    assert detail["metrics"]["passed"] == 1 and "cases" not in detail
    assert detail["pass_rate_by_domain"]["security"]["failed"] == 1
    assert c.get("/api/runs/latest").json()["run_id"] == b.run_id


async def test_findings_filters_and_detail_history(client) -> None:
    c, a, b = client
    crit = c.get(f"/api/runs/{a.run_id}/findings", params={"severity": "critical"}).json()
    assert len(crit) == 1 and crit[0]["category"] == "security.data_leakage"
    assert c.get(f"/api/runs/{a.run_id}/findings", params={"severity": "low"}).json() == []
    d = c.get(f"/api/runs/{b.run_id}/findings/FINDING-001").json()
    assert d["reproduce"].startswith("redsi reproduce FINDING-001")
    assert len(d["history"]) == 2


async def test_tests_explorer_compare_and_events(client) -> None:
    c, a, b = client
    t = c.get(f"/api/runs/{a.run_id}/tests", params={"verdict": "fail"}).json()
    assert t["total"] == 1
    case_id = t["items"][0]["id"]
    assert c.get(f"/api/runs/{a.run_id}/tests/{case_id}").json()["case"]["id"] == case_id
    cmp = c.get("/api/compare", params={"baseline": a.run_id, "candidate": b.run_id}).json()
    assert len(cmp["regressions"]) == 1 and len(cmp["resolved"]) == 1
    events = c.get(f"/api/runs/{a.run_id}/events").json()
    assert events[0]["type"] == "campaign.started"
    with c.websocket_connect(f"/api/runs/{a.run_id}/events/ws") as ws:
        first = json.loads(ws.receive_text())
        assert first["type"] == "campaign.started"


async def test_rejects_path_traversal(client) -> None:
    c, *_ = client
    assert c.get("/api/runs/..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)
    assert c.get("/api/runs/RUN-nope").status_code == 404
    assert c.get("/api/runs/not-a-run").status_code == 400
