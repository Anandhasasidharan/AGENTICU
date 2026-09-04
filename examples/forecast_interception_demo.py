"""Demo: real-time failure interception using the PROMAS forecaster.

Shows two runs of a 3-agent pipeline (a -> b -> c):
  - WITHOUT interception: forecast predicts 75% P(failure) for
    agent_b -> agent_c, handoff proceeds, agent_c crashes on
    corrupted data
  - WITH interception: same forecast, interceptor sanitizes state
    before handoff completes, agent_c succeeds

Usage:
    python examples/forecast_interception_demo.py
"""

from __future__ import annotations

import asyncio

from agenticu import handoff, trace
from agenticu.classification.classifier import Classifier
from agenticu.collector.storage import TraceStore
from agenticu.context import ContextScope
from agenticu.forecast.forecaster import Forecaster
from agenticu.forecast.transition_model import TransitionModel
from agenticu.models import AgentContext, FailureMode, Span, SpanStatus


async def seed_history(store: TraceStore) -> None:
    """Seed traces where agent_b -> agent_c fails 75% of the time."""
    for i in range(8):
        ok = i < 2
        spans = [
            Span(
                span_id=f"hist-{i}-h",
                trace_id=f"hist-{i}",
                span_type="handoff",
                agent_id="agent_b",
                attributes={"agenticu.target_agent": "agent_c"},
                status=SpanStatus.OK,
            ),
        ]
        if not ok:
            spans.append(
                Span(
                    span_id=f"hist-{i}-f",
                    trace_id=f"hist-{i}",
                    span_type="agent",
                    agent_id="agent_c",
                    parent_span_id=f"hist-{i}-h",
                    status=SpanStatus.FAILURE,
                    failure_mode=FailureMode.TASK_DERAILMENT,
                    error_message="downstream agent received corrupted state",
                )
            )
        for s in spans:
            await store.insert_span(s)


async def run_pipeline(intercept: bool = False) -> dict:
    """3-agent pipeline. If intercept=True, sanitize state before agent_c."""
    ctx = AgentContext(agent_id="pipeline", attributes={"framework": "demo"})
    store = TraceStore()
    await seed_history(store)
    model = TransitionModel()
    await model.learn(store)
    forecaster = Forecaster(model, threshold=0.3)

    @trace(agent_id="agent_a", classifier=Classifier(fast_path_only=True), store=store)
    async def agent_a(state: dict) -> dict:
        state["data"] = "clean initial data"
        return state

    @trace(agent_id="agent_b", classifier=Classifier(fast_path_only=True), store=store)
    async def agent_b(state: dict) -> dict:
        state["data"] = "error: corrupted by agent_b"
        state["source"] = "agent_b"
        return state

    @trace(agent_id="agent_c", classifier=Classifier(fast_path_only=True), store=store)
    @handoff(target_agent="agent_c")
    async def agent_c(state: dict) -> dict:
        if "error" in state.get("data", ""):
            raise ValueError(
                f"agent_c received corrupted state from {state.get('source', 'unknown')}: "
                f"{state['data']}"
            )
        state["result"] = "success"
        return state

    async def run() -> dict:
        with ContextScope(ctx):
            state = await agent_a({})
            state = await agent_b(state)

            result = await forecaster.forecast_at_handoff("agent_b", "agent_c")
            print(
                f"  Forecast P(failure) for agent_b -> agent_c: "
                f"{result.failure_probability:.0%}"
            )

            if intercept and result.threshold_exceeded:
                print(
                    f"  >>> INTERCEPTION: threshold exceeded "
                    f"({result.failure_probability:.0%} >= {forecaster.threshold:.0%}), "
                    f"sanitizing state before handoff"
                )
                state["data"] = "clean data (repaired by interceptor)"
                state["source"] = "interceptor"

            state = await agent_c(state)
        return state

    return await run()


async def main() -> None:
    print("=== Run WITHOUT interception ===")
    print("  (letting the high-risk handoff proceed)")
    try:
        outcome = await run_pipeline(intercept=False)
        print(f"  Result: {outcome}")
    except ValueError as e:
        print(f"  Result: agent_c CRASHED — {e}")

    print()
    print("=== Run WITH interception ===")
    print("  (forecast triggers recovery before the handoff)")
    try:
        outcome = await run_pipeline(intercept=True)
        print(f"  Result: {outcome}")
    except ValueError as e:
        print(f"  Result: agent_c CRASHED — {e}")

    print()
    print("Done. Interception demo shows: predict -> detect threshold -> prevent.")


if __name__ == "__main__":
    asyncio.run(main())
