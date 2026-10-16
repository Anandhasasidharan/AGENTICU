"""Prometheus metrics for AgentICU.

Exposed via the ``/metrics`` endpoint and consumed by the bundled Grafana
dashboard (``agenticu/dashboard/grafana_dashboard.json``).
"""

from __future__ import annotations

from prometheus_client import Counter

from agenticu.models import FailureMode, RecoveryAttempt

FAILURES_TOTAL = Counter(
    "agenticu_failures_total",
    "Classified agent failures by MAST failure mode.",
    ["mode", "agent_id"],
)

RECOVERY_TOTAL = Counter(
    "agenticu_recovery_total",
    "Recovery attempts by failure mode and strategy.",
    ["mode", "strategy"],
)

RECOVERY_SUCCESS = Counter(
    "agenticu_recovery_success_total",
    "Successful recovery attempts by failure mode.",
    ["mode"],
)

AGENT_SPANS = Counter(
    "agenticu_agent_spans_total",
    "Spans ingested per agent, by span type.",
    ["agent_id", "span_type"],
)


def record_failure(failure_mode: FailureMode, agent_id: str) -> None:
    """Count a classified failure."""
    FAILURES_TOTAL.labels(mode=failure_mode.value, agent_id=agent_id or "unknown").inc()


def record_recovery(
    failure_mode: FailureMode | None,
    strategy: str,
    success: bool,
) -> None:
    """Count a recovery attempt (and, when successful, the success)."""
    mode = failure_mode.value if failure_mode else "unknown"
    RECOVERY_TOTAL.labels(mode=mode, strategy=strategy or "unknown").inc()
    if success:
        RECOVERY_SUCCESS.labels(mode=mode).inc()


def record_recovery_attempt(attempt: RecoveryAttempt) -> None:
    """Count a :class:`RecoveryAttempt`."""
    record_recovery(attempt.failure_mode, attempt.strategy, bool(attempt.success))


def record_span(agent_id: str, span_type: str) -> None:
    """Count an ingested span."""
    AGENT_SPANS.labels(agent_id=agent_id or "unknown", span_type=span_type or "unknown").inc()
