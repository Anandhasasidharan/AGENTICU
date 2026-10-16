from __future__ import annotations

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from agenticu import metrics
from agenticu.api.routes import create_app
from agenticu.collector.storage import TraceStore
from agenticu.models import FailureMode, RecoveryAttempt
from agenticu.recovery.playbook_runner import PlaybookRunner
from agenticu.recovery.recovery_metrics import MetricsTracker


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_record_failure_increments_counter():
    labels = {"mode": FailureMode.STEP_REPETITION.value, "agent_id": "metrics-test-agent"}
    before = _sample("agenticu_failures_total", labels)
    metrics.record_failure(FailureMode.STEP_REPETITION, "metrics-test-agent")
    assert _sample("agenticu_failures_total", labels) == before + 1


def test_record_recovery_increments_total_and_success():
    total = {"mode": FailureMode.TASK_DERAILMENT.value, "strategy": "metrics-test-strategy"}
    success = {"mode": FailureMode.TASK_DERAILMENT.value}
    before_total = _sample("agenticu_recovery_total", total)
    before_success = _sample("agenticu_recovery_success_total", success)
    metrics.record_recovery(FailureMode.TASK_DERAILMENT, "metrics-test-strategy", True)
    assert _sample("agenticu_recovery_total", total) == before_total + 1
    assert _sample("agenticu_recovery_success_total", success) == before_success + 1


def test_failed_recovery_does_not_increment_success():
    success = {"mode": FailureMode.STEP_REPETITION.value}
    before = _sample("agenticu_recovery_success_total", success)
    metrics.record_recovery(FailureMode.STEP_REPETITION, "metrics-test-fail", False)
    assert _sample("agenticu_recovery_success_total", success) == before


def test_metrics_tracker_feeds_prometheus():
    tracker = MetricsTracker()
    labels = {"mode": FailureMode.STEP_REPETITION.value, "strategy": "metrics-test-tracker"}
    before = _sample("agenticu_recovery_total", labels)
    tracker.record(
        RecoveryAttempt(
            failure_mode=FailureMode.STEP_REPETITION,
            strategy="metrics-test-tracker",
            success=True,
        )
    )
    assert _sample("agenticu_recovery_total", labels) == before + 1


def test_metrics_endpoint_serves_prometheus_text():
    store = TraceStore()
    tracker = MetricsTracker()
    app = create_app(
        store=store,
        runner=PlaybookRunner(store=store, metrics=tracker, cooldown_seconds=0),
        metrics=tracker,
    )
    metrics.record_failure(FailureMode.STEP_REPETITION, "metrics-test-endpoint")
    resp = TestClient(app).get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "agenticu_failures_total" in resp.text


def test_grafana_dashboard_references_emitted_metrics():
    """The bundled dashboard must query the metric names AgentICU emits."""
    import json
    from importlib.resources import files

    dashboard = json.loads((files("agenticu") / "dashboard" / "grafana_dashboard.json").read_text())
    exprs = " ".join(t["expr"] for p in dashboard["panels"] for t in p["targets"])
    for name in [
        "agenticu_failures_total",
        "agenticu_recovery_total",
        "agenticu_recovery_success_total",
        "agenticu_agent_spans_total",
    ]:
        assert name in exprs
