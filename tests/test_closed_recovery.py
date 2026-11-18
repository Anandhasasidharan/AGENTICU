from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agenticu import trace
from agenticu.api.routes import create_app
from agenticu.attribution.causal_attributor import CausalAttributor
from agenticu.classification.classifier import Classifier
from agenticu.collector.database import migrate_store, open_store
from agenticu.collector.http_exporter import _request
from agenticu.collector.pipeline import IngestionPipeline
from agenticu.models import FailureMode, RecoveryOutcome
from agenticu.recovery.escalation import EscalationService
from agenticu.recovery.playbook_registry import get_playbook
from agenticu.recovery.playbook_runner import PlaybookRunner
from agenticu.recovery.recovery_metrics import MetricsTracker

SCENARIOS = [
    ("1.1", "Despite the instruction, the agent still sent an invoice"),
    ("1.2", "Acting as a billing approver without being assigned"),
    ("1.3", "Agent kept repeating the same step"),
    ("1.4", "I don't have context for this discussion"),
    ("1.5", "Continuing after completion"),
    ("2.1", "Reset the conversation history"),
    ("2.2", "The instructions are ambiguous and I'm proceeding"),
    ("2.3", "Started working on an unrelated task"),
    ("2.4", "I will not share the information"),
    ("2.5", "Ignoring the other agent's notes"),
    ("2.6", "I planned to look up the price but actually sent the quote"),
    ("3.1", "The output is incomplete"),
    ("3.2", "Submitted with no verification"),
    ("3.3", "Verified as correct, but an error surfaced"),
]


@pytest.mark.parametrize(("mode", "failure"), SCENARIOS)
async def test_hook_receives_and_applies_each_classified_playbook(
    mode, failure, store, monkeypatch
):
    monkeypatch.setenv("AGENTICU__RECOVERY__AUTO_RECOVER", "true")
    directives = []

    async def apply(directive):
        directives.append(directive)
        return True

    @trace(agent_id="worker", on_failure=apply, store=store)
    async def run():
        if not directives:
            raise ValueError(failure)
        return None

    assert await run() is None
    assert len(directives) == 1
    assert directives[0].instructions
    assert directives[0].target_agent_id == "worker"
    record = (await store.get_recovery_attempts())[0]
    assert record["failure_mode"] == mode
    assert record["strategy"] == get_playbook(FailureMode(mode)).__name__
    assert record["outcome"] == RecoveryOutcome.RECOVERED


@pytest.mark.parametrize(("enabled", "limit", "expected"), [(True, 1, 2), (False, 5, 1)])
async def test_sync_hook_honors_configured_retry_limit(
    enabled, limit, expected, store, monkeypatch
):
    monkeypatch.setenv("AGENTICU__RECOVERY__AUTO_RECOVER", str(enabled))
    monkeypatch.setenv("AGENTICU__RECOVERY__MAX_RETRIES", str(limit))
    monkeypatch.setenv("AGENTICU__RECOVERY__ESCALATE_AFTER", "5")
    calls = []

    @trace(agent_id="worker", on_failure=lambda directive: True, store=store)
    def run():
        calls.append(1)
        raise RuntimeError("Agent kept repeating the same step")

    with pytest.raises(RuntimeError, match="repeating"):
        run()
    assert len(calls) == expected
    records = await store.get_recovery_attempts()
    assert [record["outcome"] for record in records] == (
        [RecoveryOutcome.FAILED] if enabled else []
    )


async def test_repeated_failures_escalate_full_trace_and_store_outcomes(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTICU__RECOVERY__AUTO_RECOVER", "true")
    monkeypatch.setenv("AGENTICU__RECOVERY__ESCALATE_AFTER", "2")
    monkeypatch.setenv("AGENTICU__RECOVERY__MAX_RETRIES", "4")
    tracer_provider = TracerProvider()
    exporter = InMemorySpanExporter()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr("agenticu.decorators.TRACER", tracer_provider.get_tracer("test"))
    monkeypatch.setattr("agenticu.decorators.configure_http_export_from_env", lambda: None)
    monkeypatch.setenv("AGENTICU_SERVER_URL", "http://test")
    seen = 0

    @trace(agent_id="worker", on_failure=lambda action: True)
    async def run():
        nonlocal seen
        seen += 1
        raise ValueError("Agent kept repeating the same step")

    @trace(agent_id="root")
    async def workflow():
        with pytest.raises(ValueError, match="repeating"):
            await run()

    await workflow()
    assert seen == 3
    serialized = _request(exporter.get_finished_spans()).SerializeToString()

    config = {"sqlite_path": str(tmp_path / "recovery.db")}
    await migrate_store(config)
    async with open_store(config) as store:
        attribution = CausalAttributor(store)
        escalation = EscalationService()
        notify = AsyncMock()
        escalation.add_hook(notify)
        pipeline = IngestionPipeline(
            store, Classifier(fast_path_only=True), attribution, escalation
        )
        metrics = MetricsTracker()
        app = create_app(store, PlaybookRunner(store, metrics), metrics, pipeline=pipeline)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            async with pipeline.running():
                for _ in range(2):
                    response = await client.post(
                        "/v1/traces",
                        content=serialized,
                        headers={"Content-Type": "application/x-protobuf"},
                    )
                    assert response.status_code == 200
            trace_id = notify.call_args.args[0]["trace_id"]
            directive = await client.post(
                "/api/v1/recover", json={"trace_id": trace_id, "failure_mode": "1.3"}
            )
            assert directive.json()["directive"]["should_retry"] is True
            assert directive.json()["success"] is None
            recovery = (await client.get("/api/v1/recovery-attempts")).json()["attempts"]
            assert [item["outcome"] for item in recovery] == ["escalated", "failed", "retried"]
            summary = (await client.get("/api/v1/metrics/recovery")).json()
            assert summary["total"] == 2
            assert summary["by_strategy_and_mode"] == [
                {
                    "strategy": "recover_step_repetition",
                    "failure_mode": "1.3",
                    "total": 2,
                    "recovered": 0,
                    "success_rate": 0.0,
                    "below_threshold": True,
                }
            ]
        notify.assert_awaited_once()
        assert {span["agent_id"] for span in notify.call_args.args[0]["trace"]} == {
            "root",
            "worker",
        }
