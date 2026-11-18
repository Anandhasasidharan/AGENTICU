"""Encode SDK recovery attempts as OpenTelemetry span events."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from opentelemetry.trace import Span as TelemetrySpan

from agenticu.models import RecoveryAttempt, RecoveryOutcome, Span

EVENT_NAME = "agenticu.recovery"


def add_event(span: TelemetrySpan, attempt: RecoveryAttempt, *, repeated: bool) -> None:
    attributes = {
        "attempt_id": attempt.attempt_id,
        "attempt_number": attempt.attempt_number,
        "strategy": attempt.strategy,
        "outcome": attempt.outcome.value,
        "started_at": attempt.started_at.isoformat(),
        "repeated": repeated,
    }
    if attempt.root_agent_id:
        attributes["root_agent_id"] = attempt.root_agent_id
    if attempt.error_message:
        attributes["error_message"] = attempt.error_message
    span.add_event(EVENT_NAME, attributes)


def read_events(span: Span) -> list[tuple[RecoveryAttempt, bool]]:
    attempts = []
    for event in span.events:
        if event.name != EVENT_NAME:
            continue
        try:
            attributes = event.attributes
            outcome = RecoveryOutcome(attributes["outcome"])
            if outcome == RecoveryOutcome.ESCALATED:
                continue  # Escalation is recorded by the collector.
            number = attributes["attempt_number"]
            strategy = attributes["strategy"]
            started = datetime.fromisoformat(attributes["started_at"])
            if type(number) is not int or number < 1 or not isinstance(strategy, str):
                continue
            if started.utcoffset() is None:
                continue
            attempt = RecoveryAttempt(
                attempt_id=str(UUID(attributes["attempt_id"])),
                trace_id=span.trace_id,
                span_id=span.span_id,
                failure_mode=span.failure_mode,
                attempt_number=number,
                strategy=strategy,
                root_agent_id=str(attributes.get("root_agent_id") or span.agent_id),
                success=outcome == RecoveryOutcome.RECOVERED,
                started_at=started.astimezone(timezone.utc),
                completed_at=event.timestamp,
                error_message=str(attributes["error_message"])
                if "error_message" in attributes
                else None,
                outcome=outcome,
            )
            attempts.append((attempt, attributes.get("repeated") is True))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return attempts
