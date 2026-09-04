from __future__ import annotations

import asyncio

import pytest

from agenticu.context import (
    ContextScope,
    get_current_agent_id,
    get_current_span_id,
    get_current_trace_id,
    set_context,
)
from agenticu.models import AgentContext


def test_get_context_none():
    assert get_current_trace_id() is None
    assert get_current_agent_id() is None
    assert get_current_span_id() is None


def test_set_and_get():
    ctx = AgentContext(agent_id="a1", trace_id="t1", span_id="s1")
    set_context(ctx)
    assert get_current_agent_id() == "a1"
    assert get_current_trace_id() == "t1"
    assert get_current_span_id() == "s1"
    set_context(None)
    assert get_current_trace_id() is None


def test_context_scope():
    ctx = AgentContext(agent_id="a1")
    with ContextScope(ctx):
        assert get_current_agent_id() == "a1"
    assert get_current_agent_id() is None


@pytest.mark.asyncio
async def test_concurrent_contexts():
    results: list[str] = []

    async def worker(agent_id: str) -> None:
        ctx = AgentContext(agent_id=agent_id, trace_id=f"t-{agent_id}")
        with ContextScope(ctx):
            await asyncio.sleep(0.01)
            results.append(get_current_agent_id() or "none")

    await asyncio.gather(worker("a"), worker("b"), worker("c"))
    assert sorted(results) == ["a", "b", "c"]
