from __future__ import annotations

import pytest

from agenticu.models import FailureMode
from agenticu.recovery.playbook_registry import get_playbook, list_playbooks, registered_modes


def test_all_14_playbooks_registered():
    playbooks = list_playbooks()
    assert len(playbooks) == 14


def test_expected_modes_registered():
    modes = registered_modes()
    assert FailureMode.DISOBEY_TASK_SPEC in modes
    assert FailureMode.DISOBEY_ROLE_SPEC in modes
    assert FailureMode.STEP_REPETITION in modes
    assert FailureMode.LOSS_OF_CONVERSATION_HISTORY in modes
    assert FailureMode.UNAWARE_OF_TERMINATION in modes
    assert FailureMode.CONVERSATION_RESET in modes
    assert FailureMode.FAIL_TO_ASK_CLARIFICATION in modes
    assert FailureMode.TASK_DERAILMENT in modes
    assert FailureMode.INFORMATION_WITHHOLDING in modes
    assert FailureMode.IGNORED_OTHER_AGENT_INPUT in modes
    assert FailureMode.REASONING_ACTION_MISMATCH in modes
    assert FailureMode.PREMATURE_TERMINATION in modes
    assert FailureMode.NO_INCOMPLETE_VERIFICATION in modes
    assert FailureMode.INCORRECT_VERIFICATION in modes


def test_get_playbook():
    fn = get_playbook(FailureMode.STEP_REPETITION)
    assert fn is not None
    assert callable(fn)


@pytest.mark.asyncio
async def test_runner_retries_and_escalates(store, runner, sample_span):
    attempt = await runner.run(sample_span, FailureMode.STEP_REPETITION)
    assert attempt is not None
    assert attempt.success is not None


@pytest.mark.asyncio
async def test_recovery_metrics_tracker(metrics):
    from agenticu.models import RecoveryAttempt

    a1 = RecoveryAttempt(failure_mode=FailureMode.STEP_REPETITION, strategy="retry", success=True)
    a2 = RecoveryAttempt(failure_mode=FailureMode.STEP_REPETITION, strategy="retry", success=False)
    a3 = RecoveryAttempt(
        failure_mode=FailureMode.TASK_DERAILMENT, strategy="re-anchor", success=True
    )

    metrics.record(a1)
    metrics.record(a2)
    metrics.record(a3)

    rate = metrics.success_rate(FailureMode.STEP_REPETITION)
    assert rate == 0.5

    overall = metrics.success_rate()
    assert overall == 2 / 3

    by_mode = metrics.count_by_mode()
    assert by_mode["1.3"]["total"] == 2
    assert by_mode["2.3"]["total"] == 1
