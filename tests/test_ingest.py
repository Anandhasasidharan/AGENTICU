from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from importlib.resources import files
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from agenticu.api.routes import create_app
from agenticu.attribution.causal_attributor import CausalAttributor
from agenticu.classification.classifier import Classifier
from agenticu.collector.database import migrate_store, open_store
from agenticu.collector.pipeline import IngestionPipeline
from agenticu.collector.storage import TraceStore
from agenticu.forecast.forecaster import Forecaster
from agenticu.forecast.transition_model import TransitionModel
from agenticu.models import Span
from agenticu.recovery.escalation import EscalationService
from agenticu.recovery.playbook_runner import PlaybookRunner
from agenticu.recovery.recovery_metrics import MetricsTracker


def _app(store, api_key=""):
    metrics = MetricsTracker()
    return create_app(store, PlaybookRunner(store, metrics), metrics, api_key=api_key)


@pytest.fixture
def client():
    with TestClient(_app(TraceStore())) as client:
        yield client


def _otlp_json():
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "researcher"}}]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "ab" * 16,
                                "spanId": "01" * 8,
                                "name": "search",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000000000000001",
                                "status": {"code": 1},
                            }
                        ]
                    }
                ],
            }
        ]
    }


def test_otlp_json_round_trip(client):
    response = client.post("/v1/traces", json=_otlp_json())
    assert response.status_code == 200
    assert response.json() == {}
    trace = client.get(f"/api/v1/traces/{'ab' * 16}").json()["spans"]
    assert trace[0]["span_id"] == "01" * 8
    assert trace[0]["agent_id"] == "researcher"
    assert trace[0]["status"] == "ok"


def test_debug_ingestion_validates_the_whole_batch(client):
    valid = {"trace_id": "debug", "span_id": "span", "agent_id": "agent"}
    invalid = {**valid, "status": "unrecognized"}
    assert client.post("/ingest", json={"spans": [valid, invalid]}).status_code == 422
    assert client.get("/api/v1/traces/debug").status_code == 404

    response = client.post("/ingest", json={"spans": [valid]})
    assert response.json() == {"accepted": 1}
    assert client.get("/api/v1/traces/debug").json()["spans"][0]["span_id"] == "span"


def test_otlp_rejects_invalid_ids_and_wire_format(client):
    payload = _otlp_json()
    payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["traceId"] = "abcd"
    response = client.post("/v1/traces", json=payload)
    assert response.status_code == 400
    assert "traceId" in response.json()["detail"]

    response = client.post(
        "/v1/traces", content=b"\xff", headers={"Content-Type": "application/x-protobuf"}
    )
    assert response.status_code == 400
    assert "Invalid OTLP trace payload" in response.json()["detail"]
    assert client.post("/v1/traces", content="wrong content type").status_code == 415
    assert client.get("/api/v1/traces").json() == {"spans": []}


async def test_store_selection_uses_explicit_sqlite_migrations(tmp_path):
    storage = {"sqlite_path": str(tmp_path / "traces.db")}
    with pytest.raises(RuntimeError, match="agenticu migrate"):
        async with open_store(storage):
            pytest.fail("Unmigrated SQLite unexpectedly opened")

    await migrate_store(storage)
    await migrate_store(storage)
    async with open_store(storage) as store:
        await store.insert_spans([Span(trace_id="trace", span_id="span", input=False)])

    async with open_store(storage) as store:
        spans = await store.get_trace_by_id("trace")
        assert spans[0].input is False
        assert spans[0].start_time.tzinfo is not None
        assert await store.query_traces(offset=1) == []

    async with open_store({"sqlite_path": ""}) as store:
        assert await store.get_trace_by_id("trace") == []


async def test_postgres_dsn_takes_precedence(tmp_path, monkeypatch):
    dsn = "postgresql://user@localhost/agenticu"
    pool = AsyncMock()
    pool.fetch.side_effect = [
        [
            {"version": migration.name}
            for migration in files("agenticu").joinpath("migrations", "postgres").iterdir()
            if migration.name.endswith(".sql")
        ],
        [],
    ]
    context = MagicMock()
    context.__aenter__.return_value = pool
    create_pool = MagicMock(return_value=context)
    monkeypatch.setattr("asyncpg.create_pool", create_pool)
    async with open_store({"dsn": dsn, "sqlite_path": str(tmp_path / "traces.db")}) as store:
        await store.get_trace_by_id("trace")
    create_pool.assert_called_once_with(dsn, min_size=1, max_size=10, password=None)
    context.__aexit__.assert_awaited_once()


def test_remote_exporter_sends_decorated_spans_to_test_server():
    store = TraceStore()
    server = uvicorn.Server(
        uvicorn.Config(_app(store, api_key="demo-key"), log_level="error", ws="none")
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        address = f"http://127.0.0.1:{listener.getsockname()[1]}"
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and worker.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started

            agent = """
from opentelemetry.trace import get_tracer_provider
from agenticu import decision, handoff, tool_call, trace

@tool_call()
def tool():
    return "tool output"

@decision()
def decide():
    return "decision rationale"

@handoff(target_agent="writer")
def transfer():
    return "handoff state"

@trace(agent_id="researcher")
def run():
    tool()
    decide()
    transfer()

run()
assert get_tracer_provider().force_flush()
"""
            result = subprocess.run(
                [sys.executable, "-c", agent],
                env={
                    **os.environ,
                    "AGENTICU_SERVER_URL": address,
                    "AGENTICU__API__KEY": "demo-key",
                },
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert result.returncode == 0, result.stderr
            response = httpx.get(
                address + "/api/v1/traces",
                headers={"Authorization": "Bearer demo-key"},
            )
            assert response.status_code == 200
            spans = response.json()["spans"]
            assert {span["span_type"] for span in spans} == {
                "agent",
                "tool_call",
                "handoff",
                "decision",
            }
            assert len({span["trace_id"] for span in spans}) == 1
            stored = store._memory[spans[0]["trace_id"]]
            parent = next(span for span in stored if span.span_type == "agent")
            assert all(
                span.parent_span_id == parent.span_id for span in stored if span is not parent
            )
        finally:
            server.should_exit = True
            worker.join(5)


async def test_ingest_worker_classifies_and_forecasts_from_sqlite(tmp_path):
    storage = {"sqlite_path": str(tmp_path / "pipeline.db")}
    await migrate_store(storage)
    async with open_store(storage) as store:
        attributor = CausalAttributor(store)
        escalation = EscalationService()
        notified = AsyncMock()
        escalation.add_hook(notified)
        pipeline = IngestionPipeline(
            store, Classifier(fast_path_only=True), attributor, escalation, auto_recover=False
        )
        metrics = MetricsTracker()
        app = create_app(
            store,
            PlaybookRunner(store, metrics),
            metrics,
            attributor=attributor,
            pipeline=pipeline,
            forecaster=Forecaster(TransitionModel()),
        )
        payload = {
            "spans": [
                {
                    "span_id": "handoff",
                    "trace_id": "pipeline",
                    "span_type": "handoff",
                    "agent_id": "researcher",
                    "attributes": {"agenticu.target_agent": "writer"},
                    "start_time": "2026-01-01T00:00:00Z",
                },
                {
                    "span_id": "failed",
                    "trace_id": "pipeline",
                    "parent_span_id": "handoff",
                    "agent_id": "writer",
                    "start_time": "2026-01-01T00:00:01Z",
                    "end_time": "2026-01-01T00:00:02Z",
                    "status": "error",
                    "error_message": "Agent kept repeating the same step",
                },
            ]
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            async with pipeline.running():
                for _ in range(2):
                    response = await client.post("/ingest", json=payload)
                    assert response.json() == {"accepted": 2}
            failures = (await client.get("/api/v1/failures")).json()["failures"]
            assert len(failures) == 1
            classification = failures[0]
            assert classification["failure_mode"] == "1.3"
            assert classification["category"] == "specification"
            assert classification["severity"] == "error"
            assert classification["agent_id"] == "writer"
            assert classification["timestamp"] == "2026-01-01T00:00:02+00:00"
            forecast = await client.get(
                "/api/v1/forecast", params={"source_agent": "researcher", "target_agent": "writer"}
            )
            assert forecast.json()["failure_probability"] == 1
            attribution = await client.get(
                "/api/v1/attribution", params={"trace_id": "pipeline", "span_id": "failed"}
            )
            assert attribution.json()["root_agent_id"] == "researcher"
        notified.assert_awaited_once()
        assert notified.call_args.args[0]["failure_mode"] == "1.3"
