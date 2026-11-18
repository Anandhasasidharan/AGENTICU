"""Background classification and recovery dispatch for live ingestion."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from agenticu import metrics
from agenticu.attribution.causal_attributor import CausalAttributor
from agenticu.classification.classifier import Classifier
from agenticu.collector.storage import TraceStore
from agenticu.models import RecoveryOutcome, Span, SpanStatus
from agenticu.recovery.escalation import EscalationService
from agenticu.recovery.outcomes import read_events
from agenticu.recovery.playbook_registry import get_playbook

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """Process accepted batches in order and drain them on graceful shutdown."""

    def __init__(
        self,
        store: TraceStore,
        classifier: Classifier | None,
        attributor: CausalAttributor,
        escalation: EscalationService,
        *,
        auto_recover: bool = True,
        escalate_after: int = 2,
        queue_size: int = 100,
    ):
        self.store = store
        self.classifier = classifier
        self.attributor = attributor
        self.escalation = escalation
        self.auto_recover = auto_recover
        self.escalate_after = max(1, escalate_after)
        self.queue: asyncio.Queue[list[Span]] = asyncio.Queue(maxsize=queue_size)

    async def submit(self, spans: list[Span]) -> None:
        self.queue.put_nowait(spans)

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        worker = asyncio.create_task(self._work())
        try:
            yield
        finally:
            await self.queue.join()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    async def _work(self) -> None:
        while True:
            spans = await self.queue.get()
            try:
                await self.process(spans)
            except Exception:
                logger.exception("Could not process an accepted trace batch")
            finally:
                self.queue.task_done()

    def _classify(self, spans: list[Span]) -> None:
        for span in spans:
            if not span.failure_mode and span.status in (SpanStatus.ERROR, SpanStatus.FAILURE):
                if self.classifier is not None:
                    span.failure_mode = self.classifier.classify(span).failure_mode
            if span.failure_mode:
                span.status = SpanStatus.FAILURE

    async def process(self, spans: list[Span]) -> None:
        await asyncio.to_thread(self._classify, spans)
        await self.store.insert_spans(spans)
        for span in spans:
            metrics.record_span(span.agent_id, span.span_type)
            if not span.failure_mode:
                continue

            severity = span.attributes.get("agenticu.severity")
            if severity not in ("warning", "error", "critical"):
                severity = "error"
            created = await self.store.record_failure(
                span.trace_id,
                span.span_id,
                span.agent_id,
                span.failure_mode,
                span.error_message or "No error message captured",
                severity=severity,
                timestamp=span.end_time or span.start_time,
            )
            if created:
                metrics.record_failure(span.failure_mode, span.agent_id)

            reports = read_events(span)
            repeated_failures = 0
            for attempt, repeated in sorted(reports, key=lambda pair: pair[0].attempt_number):
                if await self.store.insert_recovery(attempt):
                    metrics.record_recovery_attempt(attempt)
                if repeated:
                    repeated_failures += 1
                if (
                    attempt.outcome == RecoveryOutcome.FAILED
                    and repeated_failures >= self.escalate_after
                ):
                    escalation = replace(
                        attempt,
                        attempt_id=str(
                            uuid5(NAMESPACE_URL, f"agenticu:escalate:{attempt.attempt_id}")
                        ),
                        outcome=RecoveryOutcome.ESCALATED,
                        success=None,
                        started_at=datetime.now(timezone.utc),
                        completed_at=datetime.now(timezone.utc),
                    )
                    if await self.store.insert_recovery(escalation):
                        await self._escalate(span, attempt.error_message or "Recovery failed")
                    break

            if created and not reports:
                if not self.auto_recover:
                    await self._escalate(span, "Auto-recovery disabled")
                elif get_playbook(span.failure_mode) is None:
                    await self._escalate(span, "No recovery playbook registered")

    async def _escalate(self, span: Span, reason: str) -> None:
        result = await self.attributor.attribute(span.trace_id, span.span_id)
        await self.escalation(
            span=span,
            failure_mode=span.failure_mode,
            reason=reason,
            root_agent_id=result.root_agent_id,
            trace=await self.store.get_trace_by_id(span.trace_id),
        )
