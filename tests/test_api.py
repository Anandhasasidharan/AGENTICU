from __future__ import annotations

from fastapi.testclient import TestClient

from agenticu.api.routes import create_app
from agenticu.collector.storage import TraceStore
from agenticu.recovery.playbook_runner import PlaybookRunner
from agenticu.recovery.recovery_metrics import MetricsTracker


def _make_app():
    store = TraceStore()
    metrics = MetricsTracker()
    runner = PlaybookRunner(store=store, metrics=metrics, cooldown_seconds=0)
    return create_app(store=store, runner=runner, metrics=metrics)


client = TestClient(_make_app())


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_metrics_endpoint():
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")


def test_list_traces_empty():
    resp = client.get("/api/v1/traces")
    assert resp.status_code == 200
    assert resp.json()["spans"] == []


def test_get_trace_not_found():
    resp = client.get("/api/v1/traces/nonexistent")
    assert resp.status_code == 404


def test_list_failures_empty():
    resp = client.get("/api/v1/failures")
    assert resp.status_code == 200
    assert resp.json()["failures"] == []


def test_recovery_metrics():
    resp = client.get("/api/v1/metrics/recovery")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "success_rate" in data


def test_recover_unknown_trace():
    resp = client.post("/api/v1/recover", json={"trace_id": "bad", "failure_mode": "1.1"})
    assert resp.status_code == 404


def test_recover_invalid_mode():
    resp = client.post("/api/v1/recover", json={"trace_id": "bad", "failure_mode": "99.99"})
    assert resp.status_code == 400
