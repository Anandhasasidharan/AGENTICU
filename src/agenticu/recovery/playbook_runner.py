from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from agenticu.collector.storage import TraceStore
from agenticu.models import FailureMode, RecoveryAction, RecoveryAttempt, Span
from agenticu.recovery.playbook_registry import get_playbook
from agenticu.recovery.recovery_metrics import MetricsTracker

logger = logging.getLogger(__name__)


class PlaybookRunner:
    """Execute recovery playbooks with retry and escalation."""

    def __init__(
        self,
        store: TraceStore,
        metrics: MetricsTracker,
        max_retries: int = 2,
        escalate_after: int = 2,
        cooldown_seconds: int = 30,
        escalation_hook: object | None = None,
    ):
        self.store = store
        self.metrics = metrics
        self.max_retries = max_retries
        self.escalate_after = escalate_after
        self.cooldown_seconds = cooldown_seconds
        self.escalation_hook = escalation_hook

    async def run(
        self,
        span: Span,
        failure_mode: FailureMode,
        root_agent_id: str | None = None,
    ) -> RecoveryAttempt:
        playbook = get_playbook(failure_mode)
        if playbook is None:
            logger.warning("No playbook registered for %s", failure_mode)
            return RecoveryAttempt(
                trace_id=span.trace_id,
                span_id=span.span_id,
                failure_mode=failure_mode,
                strategy="none",
                success=False,
                completed_at=datetime.now(timezone.utc),
                error_message=f"No playbook for {failure_mode}",
            )

        last_error: str | None = None
        target = root_agent_id or span.agent_id
        for attempt_num in range(1, self.max_retries + 1):
            attempt = RecoveryAttempt(
                trace_id=span.trace_id,
                span_id=span.span_id,
                failure_mode=failure_mode,
                attempt_number=attempt_num,
                strategy=playbook.__name__,
                root_agent_id=target,
                started_at=datetime.now(timezone.utc),
            )

            try:
                action: RecoveryAction = await playbook(span=span, store=self.store)
                attempt.success = action.should_retry
                attempt.completed_at = datetime.now(timezone.utc)
            except Exception as e:
                attempt.success = False
                attempt.error_message = str(e)
                attempt.completed_at = datetime.now(timezone.utc)
                last_error = str(e)

            await self.store.insert_recovery(attempt)
            self.metrics.record(attempt)

            if attempt.success:
                logger.info(
                    "Recovery succeeded for %s on attempt %d: %s",
                    failure_mode,
                    attempt_num,
                    action.instructions[:100],
                )
                return attempt

            last_error = attempt.error_message
            logger.warning(
                "Recovery attempt %d failed for %s: %s",
                attempt_num,
                failure_mode,
                last_error,
            )
            await asyncio.sleep(self.cooldown_seconds)

        await self._escalate(span, failure_mode, last_error or "unknown", root_agent_id)
        return RecoveryAttempt(
            trace_id=span.trace_id,
            span_id=span.span_id,
            failure_mode=failure_mode,
            attempt_number=self.max_retries,
            strategy=playbook.__name__,
            root_agent_id=root_agent_id or span.agent_id,
            success=False,
            completed_at=datetime.now(timezone.utc),
            error_message=last_error or "Max retries exceeded",
        )

    async def _escalate(
        self,
        span: Span,
        failure_mode: FailureMode,
        reason: str,
        root_agent_id: str | None = None,
    ) -> None:
        logger.warning(
            "Escalating trace %s mode %s root_agent=%s: %s",
            span.trace_id,
            failure_mode,
            root_agent_id or span.agent_id,
            reason,
        )
        if self.escalation_hook:
            await self.escalation_hook(
                span=span,
                failure_mode=failure_mode,
                reason=reason,
                root_agent_id=root_agent_id or span.agent_id,
            )
