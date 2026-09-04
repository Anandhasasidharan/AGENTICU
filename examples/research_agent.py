"""LangGraph multi-agent research system instrumented with AgentICU.

Usage:
    AGENTICU_CONFIG=config.yaml python examples/research_agent.py

Requires:
    pip install langgraph langchain-openai
"""

from __future__ import annotations

import asyncio
from typing import Any

from agenticu import decision, handoff, tool_call, trace

# ------------------------------------------------------------------ #
# Tool layer
# ------------------------------------------------------------------ #

@tool_call(return_snapshot=True)
async def search_web(query: str) -> str:
    """Simulate web search."""
    await asyncio.sleep(0.1)
    return f"Search results for '{query}': [simulated result 1, result 2, result 3]"


@tool_call
async def summarize(text: str, max_words: int = 50) -> str:
    """Simulate summarization."""
    await asyncio.sleep(0.05)
    return f"Summary: {text[:max_words]}..."


# ------------------------------------------------------------------ #
# Agent nodes (LangGraph-compatible)
# ------------------------------------------------------------------ #

@trace(agent_id="researcher")
@decision(record_rationale=True)
async def research_agent(state: dict[str, Any]) -> dict[str, Any]:
    """Research agent node — searches and collects information."""
    query = state.get("query", "")
    results = await search_web(query)
    state["research_results"] = results
    return state


@trace(agent_id="summarizer")
@handoff(target_agent="writer")
async def summarize_agent(state: dict[str, Any]) -> dict[str, Any]:
    """Summarizer agent node — condenses research into key points."""
    text = state.get("research_results", "")
    summary = await summarize(text)
    state["summary"] = summary
    return state


# ------------------------------------------------------------------ #
# LangGraph integration
# ------------------------------------------------------------------ #

def run_research(query: str) -> dict[str, Any]:
    """Minimal LangGraph-style agent loop with AgentICU instrumentation.

    In production, this would use StateGraph from langgraph.
    The decorators emit OTel spans regardless of the orchestration framework.
    """
    import asyncio

    from agenticu.context import ContextScope
    from agenticu.models import AgentContext

    state: dict[str, Any] = {"query": query}

    async def pipeline() -> dict[str, Any]:
        ctx = AgentContext(agent_id="research_pipeline", attributes={"framework": "langgraph"})
        with ContextScope(ctx):
            state = await research_agent(state)
            state = await summarize_agent(state)
            return state

    return asyncio.run(pipeline())


if __name__ == "__main__":
    result = run_research("multi-agent system failure taxonomy 2025")
    print(f"Query: {result.get('query')}")
    print(f"Summary: {result.get('summary', 'N/A')}")
    print("AgentICU instrumentation active — check traces in your OTel backend.")
