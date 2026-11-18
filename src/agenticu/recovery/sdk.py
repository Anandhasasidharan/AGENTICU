"""Run agent-owned recovery actions for traced calls."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime, timezone
from typing import Any

from opentelemetry.trace import Span as TelemetrySpan

from agenticu.api.config import load_config
from agenticu.attribution.causal_attributor import CausalAttributor
from agenticu.classification.classifier import Classifier
from agenticu.collector.storage import TraceStore
from agenticu.models import RecoveryAction, RecoveryAttempt, RecoveryOutcome, Span
from agenticu.recovery.escalation import EscalationService
from agenticu.recovery.outcomes import add_event
from agenticu.recovery.playbook_registry import get_playbook

OnFailure = Callable[[RecoveryAction], bool | None | Awaitable[bool | None]]
UNRECOVERED = object()


def run_sync_recovery(recovery: Awaitable[Any]) -> Any:
    async def run() -> Any:
        return await recovery

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run())

    context = copy_context()
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(context.run, asyncio.run, run()).result()


async def apply_recovery(
    retry: Callable[[], Awaitable[Any]],
    failure: Span,
    telemetry: TelemetrySpan,
    on_failure: OnFailure,
    classifier: Classifier | None,
    store: TraceStore | None,
    attributor: CausalAttributor | None,
    max_retries: int | None,
) -> Any:
    config = load_config()["agenticu"]
    settings = config["recovery"]
    if not settings["auto_recover"] or (classifier is None and not config["classifier"]["enabled"]):
        return UNRECOVERED
    classifier = classifier or Classifier(fast_path_only=True)
    mode = classifier.classify(failure).failure_mode
    if mode is None:
        return UNRECOVERED
    failure.failure_mode = mode
    telemetry.set_attribute("agenticu.failure_mode", mode.value)
    playbook = get_playbook(mode)
    if playbook is None:
        return UNRECOVERED

    retries = settings["max_retries"] if max_retries is None else max_retries
    escalate_after = max(1, settings["escalate_after"])
    attempts = min(retries, escalate_after)
    checkpoint_store = store if store is not None else TraceStore()
    root_agent = failure.agent_id
    if attributor:
        result = await attributor.attribute(failure.trace_id, failure.span_id)
        root_agent = result.root_agent_id or root_agent

    for number in range(1, attempts + 1):
        attempt = RecoveryAttempt(
            trace_id=failure.trace_id,
            span_id=failure.span_id,
            failure_mode=mode,
            attempt_number=number,
            strategy=playbook.__name__,
            root_agent_id=root_agent,
            outcome=RecoveryOutcome.FAILED,
            success=False,
        )
        result = UNRECOVERED
        retry_same_mode = False
        try:
            action = await playbook(span=failure, store=checkpoint_store, root_agent_id=root_agent)
            if action.target_agent_id is None:
                action.target_agent_id = root_agent
            decision = on_failure(action)
            if inspect.isawaitable(decision):
                decision = await decision
        except Exception as exc:
            attempt.error_message = str(exc)
        else:
            should_retry = action.should_retry if decision is None else decision
            if should_retry:
                if action.retry_delay > 0:
                    await asyncio.sleep(action.retry_delay)
                try:
                    result = await retry()
                except Exception as exc:
                    attempt.error_message = str(exc)
                    retry_failure = Span(error_message=str(exc), status=failure.status)
                    retry_same_mode = classifier.classify(retry_failure).failure_mode == mode
                    if retry_same_mode and number < attempts:
                        attempt.outcome = RecoveryOutcome.RETRIED
                else:
                    attempt.outcome = RecoveryOutcome.RECOVERED
                    attempt.success = True
            else:
                attempt.error_message = "Recovery hook declined to retry"
        attempt.completed_at = datetime.now(timezone.utc)
        add_event(telemetry, attempt, repeated=retry_same_mode)
        if store is not None:
            await store.insert_recovery(attempt)
        if attempt.success:
            return result
        if not retry_same_mode or number == retries or number == escalate_after:
            if number == escalate_after and retry_same_mode and not config.get("server_url"):
                escalation = EscalationService(**config["escalation"])
                trace = await checkpoint_store.get_trace_by_id(failure.trace_id)
                await escalation(
                    span=failure,
                    failure_mode=mode,
                    reason=attempt.error_message or "Recovery failed",
                    root_agent_id=root_agent,
                    trace=[*trace, failure],
                )
                if store is not None:
                    await store.insert_recovery(
                        RecoveryAttempt(
                            trace_id=failure.trace_id,
                            span_id=failure.span_id,
                            failure_mode=mode,
                            attempt_number=number,
                            strategy=attempt.strategy,
                            root_agent_id=root_agent,
                            outcome=RecoveryOutcome.ESCALATED,
                            completed_at=datetime.now(timezone.utc),
                        )
                    )
            break
    return UNRECOVERED
