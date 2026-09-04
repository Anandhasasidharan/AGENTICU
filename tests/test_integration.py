"""End-to-end integration test: full pipeline trace → classify → recover."""

from __future__ import annotations

import pytest

from agenticu.models import FailureMode, Span, SpanStatus


def test_classify_step_repetition(classifier):
    span = Span(
        span_id="s1",
        trace_id="t1",
        agent_id="test",
        input={"action": "search"},
        output={"result": "same result as before"},
        attributes={"agenticu.agent_id": "test"},
        status=SpanStatus.FAILURE,
    )
    result = classifier.classify(
        span, trace_text="agent kept repeating the same step over and over"
    )
    assert result.failure_mode == FailureMode.STEP_REPETITION
    assert result.confidence >= 0.8
    assert result.method == "pattern"


def test_classify_unknown(classifier):
    span = Span(span_id="s2", trace_id="t2", agent_id="test", status=SpanStatus.OK)
    result = classifier.classify(span, trace_text="everything is working fine")
    assert result.failure_mode is None


@pytest.mark.asyncio
async def test_full_pipeline(store, classifier, runner, sample_span):
    await store.insert_span(sample_span)
    stored = await store.get_trace_by_id(sample_span.trace_id)
    assert len(stored) == 1

    result = classifier.classify(
        sample_span, trace_text="agent kept repeating the same step over and over"
    )
    assert result.failure_mode is not None

    if result.failure_mode:
        attempt = await runner.run(sample_span, result.failure_mode)
        assert attempt is not None
        assert attempt.strategy != "none"


@pytest.mark.asyncio
async def test_store_query_failures(store, sample_span):
    await store.insert_span(sample_span)
    await store.record_failure(
        trace_id=sample_span.trace_id,
        span_id=sample_span.span_id,
        agent_id=sample_span.agent_id,
        failure_mode=FailureMode.STEP_REPETITION,
        error="repeat detected",
    )
    failures = await store.get_failures(agent_id="test-agent")
    assert len(failures) == 1
    assert failures[0]["failure_mode"] == "1.3"


@pytest.mark.asyncio
async def test_forecast_and_attribution_pipeline(store):
    """Full upgrade pipeline: learn transitions, forecast, attribute root cause."""
    from agenticu.attribution.causal_attributor import CausalAttributor
    from agenticu.forecast.forecaster import Forecaster
    from agenticu.forecast.transition_model import TransitionModel

    # Seed historical traces so the forecaster has data
    for i in range(3):
        tid = f"hist-{i}"
        spans = [
            Span(
                span_id=f"{tid}-h",
                trace_id=tid,
                span_type="handoff",
                agent_id="a",
                attributes={"agenticu.target_agent": "b"},
                status=SpanStatus.OK,
            ),
        ]
        if i < 2:
            spans.append(
                Span(
                    span_id=f"{tid}-f",
                    trace_id=tid,
                    span_type="agent",
                    agent_id="b",
                    parent_span_id=f"{tid}-h",
                    status=SpanStatus.FAILURE,
                    failure_mode=FailureMode.TASK_DERAILMENT,
                    error_message="derailed",
                )
            )
        for s in spans:
            await store.insert_span(s)

    model = TransitionModel()
    await model.learn(store)
    forecaster = Forecaster(model, threshold=0.3)
    forecast = await forecaster.forecast_at_handoff("a", "b")
    assert forecast.failure_probability == pytest.approx(2 / 3, rel=0.01)
    assert forecast.threshold_exceeded is True

    # Build a trace that fails in agent_c but was caused by agent_b
    tid = "live-trace"
    live = [
        Span(
            span_id="l1",
            trace_id=tid,
            span_type="agent",
            agent_id="a",
            parent_span_id=None,
            status=SpanStatus.OK,
        ),
        Span(
            span_id="l2",
            trace_id=tid,
            span_type="decision",
            agent_id="b",
            parent_span_id="l1",
            output="ERROR: wrong transformation applied",
            status=SpanStatus.OK,
        ),
        Span(
            span_id="l3",
            trace_id=tid,
            span_type="agent",
            agent_id="c",
            parent_span_id="l2",
            status=SpanStatus.FAILURE,
            failure_mode=FailureMode.TASK_DERAILMENT,
            error_message="c failed",
        ),
    ]
    for s in live:
        await store.insert_span(s)

    attributor = CausalAttributor(store)
    attr = await attributor.attribute(tid, "l3")
    assert attr.root_agent_id == "b"
    assert "b" in attr.attribution_chain
