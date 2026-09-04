from __future__ import annotations

import pytest

from agenticu.models import FailureMode, Span, SpanStatus
from agenticu.recovery.playbook_registry import get_playbook


def _make_span(sid: str, mode: FailureMode) -> Span:
    return Span(
        span_id=sid,
        trace_id=sid.replace("s", "t", 1),
        agent_id="test",
        status=SpanStatus.FAILURE,
        failure_mode=mode,
    )


@pytest.mark.asyncio
async def test_disobey_task_spec_playbook(store):
    span = _make_span("s1", FailureMode.DISOBEY_TASK_SPEC)
    fn = get_playbook(FailureMode.DISOBEY_TASK_SPEC)
    assert fn is not None
    result = await fn(span=span, store=store)
    assert result.should_retry is True
    assert "instructions" in dir(result)


@pytest.mark.asyncio
async def test_step_repetition_playbook(store):
    span = _make_span("s2", FailureMode.STEP_REPETITION)
    fn = get_playbook(FailureMode.STEP_REPETITION)
    assert fn is not None
    result = await fn(span=span, store=store)
    assert result.should_retry is True


@pytest.mark.asyncio
async def test_loss_of_history_playbook(store):
    span = _make_span("s3", FailureMode.LOSS_OF_CONVERSATION_HISTORY)
    fn = get_playbook(FailureMode.LOSS_OF_CONVERSATION_HISTORY)
    assert fn is not None
    result = await fn(span=span, store=store)
    assert result.should_retry is False


@pytest.mark.asyncio
async def test_task_derailment_playbook(store):
    span = _make_span("s4", FailureMode.TASK_DERAILMENT)
    fn = get_playbook(FailureMode.TASK_DERAILMENT)
    assert fn is not None
    result = await fn(span=span, store=store)
    assert result.should_retry is True


@pytest.mark.asyncio
async def test_premature_termination_playbook(store):
    span = _make_span("s5", FailureMode.PREMATURE_TERMINATION)
    fn = get_playbook(FailureMode.PREMATURE_TERMINATION)
    assert fn is not None
    result = await fn(span=span, store=store)
    assert result.should_retry is True


@pytest.mark.asyncio
async def test_incorrect_verification_playbook(store):
    span = _make_span("s6", FailureMode.INCORRECT_VERIFICATION)
    fn = get_playbook(FailureMode.INCORRECT_VERIFICATION)
    assert fn is not None
    result = await fn(span=span, store=store)
    assert result.should_retry is True


@pytest.mark.asyncio
async def test_disobey_role_spec_playbook(store):
    span = _make_span("s7", FailureMode.DISOBEY_ROLE_SPEC)
    fn = get_playbook(FailureMode.DISOBEY_ROLE_SPEC)
    assert fn is not None
    result = await fn(span=span, store=store)
    assert result.should_retry is True


@pytest.mark.asyncio
async def test_unaware_of_termination_playbook(store):
    span = _make_span("s8", FailureMode.UNAWARE_OF_TERMINATION)
    fn = get_playbook(FailureMode.UNAWARE_OF_TERMINATION)
    assert fn is not None
    result = await fn(span=span, store=store)
    assert result.should_retry is False


@pytest.mark.asyncio
async def test_conversation_reset_playbook(store):
    span = _make_span("s9", FailureMode.CONVERSATION_RESET)
    fn = get_playbook(FailureMode.CONVERSATION_RESET)
    assert fn is not None
    result = await fn(span=span, store=store)
    assert result.should_retry is True


@pytest.mark.asyncio
async def test_fail_to_ask_clarification_playbook(store):
    span = _make_span("s10", FailureMode.FAIL_TO_ASK_CLARIFICATION)
    fn = get_playbook(FailureMode.FAIL_TO_ASK_CLARIFICATION)
    assert fn is not None
    result = await fn(span=span, store=store)
    assert result.should_retry is True


@pytest.mark.asyncio
async def test_information_withholding_playbook(store):
    span = _make_span("s11", FailureMode.INFORMATION_WITHHOLDING)
    fn = get_playbook(FailureMode.INFORMATION_WITHHOLDING)
    assert fn is not None
    result = await fn(span=span, store=store)
    assert result.should_retry is True


@pytest.mark.asyncio
async def test_ignored_other_agent_input_playbook(store):
    span = _make_span("s12", FailureMode.IGNORED_OTHER_AGENT_INPUT)
    fn = get_playbook(FailureMode.IGNORED_OTHER_AGENT_INPUT)
    assert fn is not None
    result = await fn(span=span, store=store)
    assert result.should_retry is True


@pytest.mark.asyncio
async def test_reasoning_action_mismatch_playbook(store):
    span = _make_span("s13", FailureMode.REASONING_ACTION_MISMATCH)
    fn = get_playbook(FailureMode.REASONING_ACTION_MISMATCH)
    assert fn is not None
    result = await fn(span=span, store=store)
    assert result.should_retry is True


@pytest.mark.asyncio
async def test_no_incomplete_verification_playbook(store):
    span = _make_span("s14", FailureMode.NO_INCOMPLETE_VERIFICATION)
    fn = get_playbook(FailureMode.NO_INCOMPLETE_VERIFICATION)
    assert fn is not None
    result = await fn(span=span, store=store)
    assert result.should_retry is True
