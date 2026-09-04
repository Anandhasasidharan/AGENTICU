from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agenticu.collector.storage import TraceStore
from agenticu.models import FailureMode, Span, SpanStatus


@pytest.mark.asyncio
async def test_max_traces_eviction():
    store = TraceStore(max_traces=2)
    for i in range(5):
        span = Span(span_id=f"s{i}", trace_id=f"t{i}", agent_id="test", status=SpanStatus.OK)
        await store.insert_span(span)
    assert len(store._memory) <= 2


@pytest.mark.asyncio
async def test_pool_path_uses_pool():
    pool = AsyncMock()
    pool.execute = AsyncMock()
    store = TraceStore(pool=pool)
    span = Span(span_id="s1", trace_id="t1", status=SpanStatus.OK)
    await store.insert_span(span)
    pool.execute.assert_called_once()


@pytest.mark.asyncio
async def test_pool_get_trace_by_id():
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=[])
    store = TraceStore(pool=pool)
    result = await store.get_trace_by_id("t1")
    assert result == []
    pool.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_get_recovery_stats_empty():
    store = TraceStore()
    stats = await store.get_recovery_stats()
    assert stats == {"total": 0, "succeeded": 0, "failed": 0}


@pytest.mark.asyncio
async def test_insert_and_get_trace():
    store = TraceStore()
    span = Span(span_id="s1", trace_id="t1", agent_id="a1", status=SpanStatus.OK)
    await store.insert_span(span)
    spans = await store.get_trace_by_id("t1")
    assert len(spans) == 1
    assert spans[0].span_id == "s1"


@pytest.mark.asyncio
async def test_query_traces_filters_by_agent():
    store = TraceStore()
    for i in range(3):
        span = Span(span_id=f"s{i}", trace_id="t1", agent_id=f"a{i}", status=SpanStatus.OK)
        await store.insert_span(span)
    results = await store.query_traces(agent_id="a1")
    assert len(results) == 1
    assert results[0].agent_id == "a1"


@pytest.mark.asyncio
async def test_record_and_get_failures():
    store = TraceStore()
    await store.record_failure("t1", "s1", "a1", FailureMode.STEP_REPETITION, "error")
    failures = await store.get_failures()
    assert len(failures) == 1
    assert failures[0]["failure_mode"] == "1.3"
