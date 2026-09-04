from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agenticu.models import FailureMode, Span, SpanStatus
from agenticu.recovery.escalation import EscalationService


@pytest.mark.asyncio
async def test_build_payload():
    svc = EscalationService()
    span = Span(
        span_id="s1",
        trace_id="t1",
        agent_id="a1",
        status=SpanStatus.FAILURE,
        error_message="oops",
    )
    payload = svc._build_payload(span, FailureMode.STEP_REPETITION, "max retries exceeded")
    assert payload["trace_id"] == "t1"
    assert payload["failure_mode"] == "1.3"
    assert payload["error"] == "oops"


@pytest.mark.asyncio
async def test_noop_when_no_hooks_configured():
    svc = EscalationService()
    span = Span(span_id="s1", trace_id="t1", agent_id="a1", status=SpanStatus.FAILURE)
    await svc(span=span, failure_mode=FailureMode.STEP_REPETITION, reason="test")


@pytest.mark.asyncio
async def test_custom_hook_invoked():
    hook = AsyncMock()
    svc = EscalationService()
    svc.add_hook(hook)
    span = Span(span_id="s1", trace_id="t1", agent_id="a1", status=SpanStatus.FAILURE)
    await svc(span=span, failure_mode=FailureMode.STEP_REPETITION, reason="test")
    hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_slack_webhook_called(respx_mock):
    webhook_url = "https://hooks.slack.com/test"
    route = respx_mock.post(webhook_url).respond(status_code=200)
    svc = EscalationService(slack_webhook=webhook_url)
    span = Span(
        span_id="s1",
        trace_id="t1",
        agent_id="a1",
        status=SpanStatus.FAILURE,
        error_message="err",
    )
    await svc(span=span, failure_mode=FailureMode.STEP_REPETITION, reason="test")
    assert route.called
