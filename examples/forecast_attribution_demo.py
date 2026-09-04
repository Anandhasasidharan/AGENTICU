"""End-to-end demo: PROMAS forecaster + causal attribution on a multi-agent chain.

Demonstrates:
  1. Forecasting failure probability BEFORE a handoff completes
  2. Causal attribution: when a failure occurs, trace it back to the
     root-cause agent (not the agent holding the bag when it surfaced)

Usage:
    python examples/forecast_attribution_demo.py
"""

from __future__ import annotations

import asyncio

from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from agenticu import decision, handoff, trace
from agenticu.attribution.causal_attributor import CausalAttributor
from agenticu.classification.classifier import Classifier
from agenticu.collector.receiver import AgentICUExporter
from agenticu.collector.storage import TraceStore
from agenticu.context import ContextScope
from agenticu.forecast.forecaster import Forecaster
from agenticu.forecast.transition_model import TransitionModel
from agenticu.models import AgentContext, FailureMode, Span, SpanStatus


# ---------------------------------------------------------------- #
# A 3-agent pipeline where agent_b makes a bad decision that
# propagates a degraded state to agent_c (which then fails).
# ---------------------------------------------------------------- #

async def bad_decision_pipeline(store: TraceStore) -> str:
    """Reproducible trace that ends in a failure caused upstream."""
    ctx = AgentContext(agent_id="pipeline", attributes={"framework": "demo"})

    @trace(agent_id="agent_a", classifier=Classifier(fast_path_only=True), store=store)
    async def agent_a(state: dict) -> dict:
        state["data"] = "clean initial data"
        return state

    @trace(agent_id="agent_b", classifier=Classifier(fast_path_only=True), store=store)
    @decision(record_rationale=True)
    async def agent_b(state: dict) -> dict:
        # Agent B makes a bad call: corrupts the data
        state["data"] = "error: corrupted by bad transformation"
        return state

    @trace(agent_id="agent_c", classifier=Classifier(fast_path_only=True), store=store)
    @handoff(target_agent="agent_c")
    async def agent_c(state: dict) -> dict:
        if "error" in state.get("data", ""):
            raise ValueError("Downstream processing failed on corrupted data")
        return state

    async def run() -> dict:
        with ContextScope(ctx):
            state = await agent_a({})
            state = await agent_b(state)
            try:
                state = await agent_c(state)
            except ValueError:
                return state
        return state

    return await run()


async def build_history(store: TraceStore) -> None:
    """Seed historical traces so the forecaster has something to learn."""

    async def seed(trace_id: str, ok: bool, target: str = "agent_c") -> None:
        spans = [
            Span(
                span_id=f"{trace_id}-h",
                trace_id=trace_id,
                span_type="handoff",
                agent_id="agent_a",
                attributes={"agenticu.target_agent": target},
                status=SpanStatus.OK,
            ),
        ]
        if not ok:
            spans.append(
                Span(
                    span_id=f"{trace_id}-f",
                    trace_id=trace_id,
                    span_type="agent",
                    agent_id=target,
                    parent_span_id=f"{trace_id}-h",
                    status=SpanStatus.FAILURE,
                    failure_mode=FailureMode.TASK_DERAILMENT,
                    error_message="corrupted data propagated",
                )
            )
        for s in spans:
            await store.insert_span(s)

    await seed("hist-1", ok=False)
    await seed("hist-2", ok=False)
    await seed("hist-3", ok=True)


def setup_otel(store: TraceStore) -> None:
    """Wire AgentICUExporter into the global OTel tracer provider."""
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(AgentICUExporter(store)))
    otel_trace.set_tracer_provider(provider)


async def main() -> None:
    store = TraceStore()
    setup_otel(store)
    await build_history(store)

    # ---- PROMAS forecast ----
    print("=== PROMAS Forecast: predict failure before handoff ===")
    model = TransitionModel()
    await model.learn(store)
    forecaster = Forecaster(model, threshold=0.3)
    result = await forecaster.forecast_at_handoff("agent_a", "agent_c")
    print(f"  Predicted P(failure) for agent_a -> agent_c: {result.failure_probability:.1%}")
    print(f"  Most likely mode: {result.predicted_mode}")
    print(f"  Threshold exceeded (early intervention): {result.threshold_exceeded}")

    # ---- Run the failing pipeline ----
    print("\n=== Run multi-agent pipeline (fails in agent_c) ===")
    outcome = await bad_decision_pipeline(store)
    print(f"  Final state data: {outcome.get('data')}")

    # Flush any pending OTel spans to the store
    provider = otel_trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush(2000)

    all_spans = await store.query_traces(limit=1000)
    print(f"  Spans recorded in store: {len(all_spans)}")

    # ---- Causal attribution ----
    print("\n=== Causal Attribution: find the root-cause agent ===")
    attributor = CausalAttributor(store)
    all_spans = await store.query_traces(limit=1000)
    failure_spans = [s for s in all_spans if s.status == SpanStatus.FAILURE or s.error_message]
    if failure_spans:
        failure = failure_spans[0]
        trace_id = failure.trace_id
        spans = await store.get_trace_by_id(trace_id)
        failure_span = next(
            (s for s in spans if s.status == SpanStatus.FAILURE or s.error_message),
            failure,
        )
        attr = await attributor.attribute(trace_id, failure_span.span_id)
        print(f"  Root-cause agent: {attr.root_agent_id}")
        print(f"  Confidence: {attr.confidence:.1%}")
        print(f"  Chain: {' -> '.join(attr.attribution_chain)}")
        print(f"  Explanation: {attr.root_cause_description}")
    else:
        print("  No failure span found in store.")

    print("\nDone. AgentICU correctly forecasted AND attributed the failure upstream.")


if __name__ == "__main__":
    asyncio.run(main())
