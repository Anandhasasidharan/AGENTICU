from __future__ import annotations

import pytest

from agenticu import decision, handoff, tool_call, trace
from agenticu.context import ContextScope, get_current_agent_id
from agenticu.models import AgentContext


def test_trace_basic():
    @trace(agent_id="test")
    def my_func() -> str:
        return "hello"

    assert my_func() == "hello"


def test_trace_with_agent_context():
    @trace(agent_id="worker")
    def process(x: int) -> int:
        return x * 2

    ctx = AgentContext(agent_id="worker", trace_id="t1")
    with ContextScope(ctx):
        result = process(21)

    assert result == 42


@pytest.mark.asyncio
async def test_trace_async():
    @trace(agent_id="async-agent")
    async def fetch() -> str:
        return "data"

    result = await fetch()
    assert result == "data"


def test_tool_call():
    @tool_call(return_snapshot=True)
    def search(q: str) -> str:
        return f"results for {q}"

    ctx = AgentContext(agent_id="test")
    with ContextScope(ctx):
        assert search("test") == "results for test"


def test_handoff():
    @handoff(target_agent="writer")
    def transfer(data: str) -> str:
        return f"handoff: {data}"

    ctx = AgentContext(agent_id="reader")
    with ContextScope(ctx):
        assert transfer("data") == "handoff: data"


def test_decision():
    @decision(record_rationale=True)
    def choose(option: str) -> str:
        return option

    ctx = AgentContext(agent_id="test")
    with ContextScope(ctx):
        assert choose("a") == "a"


def test_decorator_composition():
    @trace(agent_id="composed")
    @tool_call()
    def composed_func(x: int) -> int:
        return x + 1

    ctx = AgentContext(agent_id="composed")
    with ContextScope(ctx):
        assert composed_func(1) == 2


def test_context_isolation():
    ctx1 = AgentContext(agent_id="agent1", trace_id="t1")
    ctx2 = AgentContext(agent_id="agent2", trace_id="t2")

    with ContextScope(ctx1):
        assert get_current_agent_id() == "agent1"
        with ContextScope(ctx2):
            assert get_current_agent_id() == "agent2"
        assert get_current_agent_id() == "agent1"


def test_trace_error_propagation():
    @trace(agent_id="test")
    def broken() -> None:
        raise ValueError("oops")

    with pytest.raises(ValueError, match="oops"):
        broken()


@pytest.mark.asyncio
async def test_trace_async_error():
    @trace(agent_id="test")
    async def broken() -> None:
        raise RuntimeError("async fail")

    with pytest.raises(RuntimeError, match="async fail"):
        await broken()
