from __future__ import annotations

import pytest

from agenticu.forecast.forecaster import Forecaster
from agenticu.forecast.transition_model import TransitionModel
from agenticu.models import FailureMode, Span, SpanStatus


class TestTransitionModel:
    def test_empty_model_returns_zero(self):
        model = TransitionModel()
        prob, mode, conf, samples = model.predict("a", "b")
        assert prob == 0.0
        assert mode is None
        assert conf == 0.0
        assert samples == 0

    def test_learn_from_handoffs(self, store):
        model = TransitionModel()
        _seed_trace(store, [("agent_a", "agent_b")], failures=[])
        _seed_trace(store, [("agent_a", "agent_b")], failures=[])
        _seed_trace(store, [("agent_a", "agent_b")], failures=[FailureMode.STEP_REPETITION])

        import asyncio

        asyncio.run(model.learn(store))

        prob, mode, conf, samples = model.predict("agent_a", "agent_b")
        assert samples == 3
        assert prob == pytest.approx(1 / 3, rel=0.01)
        assert mode == FailureMode.STEP_REPETITION
        assert 0 < conf <= 1.0

    def test_learn_respects_different_pairs(self, store):
        model = TransitionModel()
        _seed_trace(store, [("a", "b")], failures=[FailureMode.STEP_REPETITION])
        _seed_trace(store, [("a", "c")], failures=[])
        _seed_trace(store, [("a", "c")], failures=[])

        import asyncio

        asyncio.run(model.learn(store))

        prob_ab, _, _, _ = model.predict("a", "b")
        prob_ac, _, _, _ = model.predict("a", "c")
        assert prob_ab == 1.0
        assert prob_ac == 0.0

    def test_confidence_scale(self):
        model = TransitionModel()
        for _ in range(10):
            key = ("a", "b")
            model._handoff_counts[key] += 1

        _, _, conf, _ = model.predict("a", "b")
        assert conf == 1.0

    def test_known_transitions(self, store):
        model = TransitionModel()
        _seed_trace(store, [("x", "y"), ("y", "z")], failures=[])

        import asyncio

        asyncio.run(model.learn(store))

        assert ("x", "y") in model.known_transitions
        assert ("y", "z") in model.known_transitions


class TestForecaster:
    def test_forecast_at_handoff(self, store):
        model = TransitionModel()
        _seed_trace(store, [("a", "b")], failures=[FailureMode.STEP_REPETITION])
        _seed_trace(store, [("a", "b")], failures=[])

        import asyncio

        asyncio.run(model.learn(store))

        forecaster = Forecaster(model, threshold=0.3)
        result = asyncio.run(forecaster.forecast_at_handoff("a", "b"))

        assert result.source_agent == "a"
        assert result.target_agent == "b"
        assert result.failure_probability == 0.5
        assert result.samples_seen == 2
        assert result.threshold_exceeded is True

    def test_forecast_below_threshold(self, store):
        model = TransitionModel()
        _seed_trace(store, [("a", "b")], failures=[FailureMode.STEP_REPETITION])
        _seed_trace(store, [("a", "b")], failures=[])
        _seed_trace(store, [("a", "b")], failures=[])

        import asyncio

        asyncio.run(model.learn(store))

        forecaster = Forecaster(model, threshold=0.5)
        result = asyncio.run(forecaster.forecast_at_handoff("a", "b"))

        assert result.failure_probability == pytest.approx(1 / 3, rel=0.01)
        assert result.threshold_exceeded is False

    def test_forecast_no_data(self):
        model = TransitionModel()
        forecaster = Forecaster(model)

        import asyncio

        result = asyncio.run(forecaster.forecast_at_handoff("unknown", "unknown"))

        assert result.failure_probability == 0.0
        assert result.confidence == 0.0
        assert result.samples_seen == 0
        assert result.threshold_exceeded is False

    def test_forecast_trace(self, store):
        model = TransitionModel()
        trace_id = "forecast-trace-1"
        spans = [
            Span(
                span_id="s1",
                trace_id=trace_id,
                span_type="agent",
                agent_id="a",
                status=SpanStatus.OK,
            ),
            Span(
                span_id="s2",
                trace_id=trace_id,
                span_type="handoff",
                agent_id="a",
                attributes={"agenticu.target_agent": "b"},
                status=SpanStatus.OK,
            ),
            Span(
                span_id="s3",
                trace_id=trace_id,
                span_type="agent",
                agent_id="b",
                status=SpanStatus.OK,
            ),
        ]
        for s in spans:
            import asyncio

            asyncio.run(store.insert_span(s))

        _seed_trace(store, [("a", "b")], failures=[FailureMode.TASK_DERAILMENT])
        import asyncio

        asyncio.run(model.learn(store))

        forecaster = Forecaster(model)
        results = asyncio.run(forecaster.forecast_trace(trace_id, store))

        assert len(results) == 1
        assert results[0].source_agent == "a"
        assert results[0].target_agent == "b"


def _seed_trace(
    store,
    handoff_pairs: list[tuple[str, str]],
    failures: list[FailureMode],
):
    trace_id = f"seed-{id(handoff_pairs)}-{id(failures)}"
    import asyncio

    for i, (src, tgt) in enumerate(handoff_pairs):
        span = Span(
            span_id=f"{trace_id}-h{i}",
            trace_id=trace_id,
            span_type="handoff",
            agent_id=src,
            attributes={"agenticu.target_agent": tgt},
            status=SpanStatus.OK,
        )
        if i < len(failures):
            span.failure_mode = failures[i]
            span.status = SpanStatus.FAILURE
        asyncio.run(store.insert_span(span))
