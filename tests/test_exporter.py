from __future__ import annotations

from datetime import datetime

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace import Status as OTelStatus
from opentelemetry.trace import SpanContext, SpanKind, StatusCode, TraceFlags

from agenticu.collector.processor import TraceProcessor
from agenticu.collector.receiver import AgentICUExporter
from agenticu.collector.storage import TraceStore


def _make_otel_span(
    span_id: int = 1,
    trace_id: int = 1,
    status_code: StatusCode = StatusCode.OK,
    attributes: dict | None = None,
) -> ReadableSpan:
    ctx = SpanContext(
        trace_id=trace_id,
        span_id=span_id,
        is_remote=False,
        trace_flags=TraceFlags(1),
    )
    span = ReadableSpan(
        name="test",
        context=ctx,
        parent=None,
        attributes=attributes or {},
        start_time=datetime.now(),
        end_time=datetime.now(),
        status=OTelStatus(status_code),
        kind=SpanKind.INTERNAL,
    )
    return span


@pytest.mark.asyncio
async def test_export_ok_span():
    store = TraceStore()
    exporter = AgentICUExporter(store=store, processor=TraceProcessor())
    otel_span = _make_otel_span(span_id=1, trace_id=1)
    result = exporter.export([otel_span])
    assert result.value == 0
    spans = await store.get_trace_by_id(hex(1)[2:])
    assert len(spans) == 1


def test_export_error_span():
    store = TraceStore()
    exporter = AgentICUExporter(store=store, processor=TraceProcessor())
    otel_span = _make_otel_span(span_id=2, trace_id=2, status_code=StatusCode.ERROR)
    result = exporter.export([otel_span])
    assert result.value == 0


@pytest.mark.asyncio
async def test_export_failure_span_records_failure():
    store = TraceStore()
    exporter = AgentICUExporter(store=store, processor=TraceProcessor())
    otel_span = _make_otel_span(
        span_id=3,
        trace_id=3,
        status_code=StatusCode.ERROR,
        attributes={
            "agenticu.error": "tool failed",
            "agenticu.agent_id": "a1",
            "agenticu.failure_mode": "1.3",
        },
    )
    exporter.export([otel_span])
    failures = await store.get_failures()
    assert len(failures) >= 1


def test_shutdown_and_force_flush():
    store = TraceStore()
    exporter = AgentICUExporter(store=store)
    exporter.shutdown()
    assert exporter.force_flush() is True


def test_duplicate_span_in_sequential_exports():
    store = TraceStore()
    processor = TraceProcessor()
    exporter = AgentICUExporter(store=store, processor=processor)
    otel_span = _make_otel_span(span_id=5, trace_id=5)
    exporter.export([otel_span])
    exporter.export([otel_span])
