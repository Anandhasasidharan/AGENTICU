from __future__ import annotations

import pytest

from agenticu.attribution.causal_attributor import CausalAttributor, _suggests_error
from agenticu.models import Span, SpanStatus


class TestCausalAttributor:
    @pytest.mark.asyncio
    async def test_single_agent_no_handoff(self, store):
        span = Span(
            span_id="s1",
            trace_id="t1",
            agent_id="agent_a",
            span_type="agent",
            status=SpanStatus.FAILURE,
            failure_mode="1.1",
            error_message="violated constraint",
        )
        await store.insert_span(span)

        attributor = CausalAttributor(store)
        result = await attributor.attribute("t1", "s1")

        assert result.root_agent_id == "agent_a"
        assert result.confidence == 0.9
        assert result.attribution_chain == ["agent_a"]

    @pytest.mark.asyncio
    async def test_two_agent_handoff_chain(self, store):
        spans = [
            Span(
                span_id="s1",
                trace_id="t1",
                span_type="agent",
                agent_id="agent_a",
                parent_span_id=None,
                status=SpanStatus.OK,
            ),
            Span(
                span_id="s2",
                trace_id="t1",
                span_type="handoff",
                agent_id="agent_a",
                parent_span_id="s1",
                attributes={"agenticu.target_agent": "agent_b"},
                output="handing off control",
                status=SpanStatus.OK,
            ),
            Span(
                span_id="s3",
                trace_id="t1",
                span_type="agent",
                agent_id="agent_b",
                parent_span_id="s2",
                status=SpanStatus.FAILURE,
                failure_mode="1.3",
                error_message="repeated step",
            ),
        ]
        for s in spans:
            await store.insert_span(s)

        attributor = CausalAttributor(store)
        result = await attributor.attribute("t1", "s3")

        assert result.attribution_chain == ["agent_a", "agent_b"]
        assert result.root_agent_id == "agent_a"
        assert result.confidence == 0.6

    @pytest.mark.asyncio
    async def test_decision_with_error_root_cause(self, store):
        spans = [
            Span(
                span_id="s1",
                trace_id="t1",
                span_type="agent",
                agent_id="agent_a",
                parent_span_id=None,
                status=SpanStatus.OK,
            ),
            Span(
                span_id="s2",
                trace_id="t1",
                span_type="decision",
                agent_id="agent_a",
                parent_span_id="s1",
                output="ERROR: chose wrong API endpoint",
                status=SpanStatus.OK,
            ),
            Span(
                span_id="s3",
                trace_id="t1",
                span_type="handoff",
                agent_id="agent_a",
                parent_span_id="s2",
                attributes={"agenticu.target_agent": "agent_b"},
                output="passing control",
                status=SpanStatus.OK,
            ),
            Span(
                span_id="s4",
                trace_id="t1",
                span_type="agent",
                agent_id="agent_b",
                parent_span_id="s3",
                status=SpanStatus.FAILURE,
                failure_mode="1.1",
                error_message="wrong API used",
            ),
        ]
        for s in spans:
            await store.insert_span(s)

        attributor = CausalAttributor(store)
        result = await attributor.attribute("t1", "s4")

        assert result.root_agent_id == "agent_a"
        assert result.confidence == 0.85
        assert "ERROR: chose wrong API" in result.root_cause_description

    @pytest.mark.asyncio
    async def test_handoff_with_degraded_state(self, store):
        spans = [
            Span(
                span_id="s1",
                trace_id="t1",
                span_type="agent",
                agent_id="agent_a",
                parent_span_id=None,
                status=SpanStatus.OK,
            ),
            Span(
                span_id="s2",
                trace_id="t1",
                span_type="handoff",
                agent_id="agent_a",
                parent_span_id="s1",
                attributes={"agenticu.target_agent": "agent_b"},
                output="failed response: timeout connecting to API",
                status=SpanStatus.OK,
            ),
            Span(
                span_id="s3",
                trace_id="t1",
                span_type="agent",
                agent_id="agent_b",
                parent_span_id="s2",
                status=SpanStatus.FAILURE,
                failure_mode="2.3",
                error_message="task derailment",
            ),
        ]
        for s in spans:
            await store.insert_span(s)

        attributor = CausalAttributor(store)
        result = await attributor.attribute("t1", "s3")

        assert result.root_agent_id == "agent_a"
        assert result.confidence == 0.85
        assert "degraded state" in result.root_cause_description

    @pytest.mark.asyncio
    async def test_unknown_trace_id(self, store):
        attributor = CausalAttributor(store)
        result = await attributor.attribute("nonexistent", "s1")

        assert result.root_agent_id is None
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_three_agent_chain(self, store):
        spans = [
            Span(
                span_id="s1",
                trace_id="t1",
                span_type="agent",
                agent_id="agent_a",
                parent_span_id=None,
                status=SpanStatus.OK,
            ),
            Span(
                span_id="s2",
                trace_id="t1",
                span_type="handoff",
                agent_id="agent_a",
                parent_span_id="s1",
                attributes={"agenticu.target_agent": "agent_b"},
                output="all good",
                status=SpanStatus.OK,
            ),
            Span(
                span_id="s3",
                trace_id="t1",
                span_type="agent",
                agent_id="agent_b",
                parent_span_id="s2",
                status=SpanStatus.OK,
            ),
            Span(
                span_id="s4",
                trace_id="t1",
                span_type="handoff",
                agent_id="agent_b",
                parent_span_id="s3",
                attributes={"agenticu.target_agent": "agent_c"},
                output="error: results invalid",
                status=SpanStatus.OK,
            ),
            Span(
                span_id="s5",
                trace_id="t1",
                span_type="agent",
                agent_id="agent_c",
                parent_span_id="s4",
                status=SpanStatus.FAILURE,
                failure_mode="1.4",
                error_message="bad data propagated",
            ),
        ]
        for s in spans:
            await store.insert_span(s)

        attributor = CausalAttributor(store)
        result = await attributor.attribute("t1", "s5")

        assert result.root_agent_id == "agent_b"
        assert result.attribution_chain == ["agent_a", "agent_b", "agent_c"]
        assert "degraded state" in result.root_cause_description


class TestHelpers:
    def test_suggests_error_true(self):
        assert _suggests_error("this is an error message") is True
        assert _suggests_error("FAILED: timeout") is True
        assert _suggests_error("exception raised") is True

    def test_suggests_error_false(self):
        assert _suggests_error("everything is working fine") is False
        assert _suggests_error("completed successfully") is False
