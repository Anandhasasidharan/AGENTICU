from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from agenticu.classification.classifier import Classifier
from agenticu.collector.storage import TraceStore
from agenticu.forecast.transition_model import TransitionModel
from agenticu.models import Span, SpanStatus

logger = logging.getLogger(__name__)


class OutcomeTracker:
    """Background loop that feeds completed trace outcomes back into the forecaster
    and classifier.

    Periodically polls the TraceStore for new completed traces:
      - Calls TransitionModel.learn() to update transition probabilities
      - Classifies new failures and adds them to SignatureDB as training examples

    Closes the architecture feedback loop shown in the AgentICU pipeline diagram.

    Usage:
        tracker = OutcomeTracker(store, model, classifier, interval_secs=30)
        await tracker.start()
        # ... agenticu runs ...
        await tracker.stop()
    """

    def __init__(
        self,
        store: TraceStore,
        transition_model: TransitionModel,
        classifier: Classifier | None = None,
        interval_secs: float = 60.0,
        min_new_traces: int = 5,
    ):
        self.store = store
        self.transition_model = transition_model
        self.classifier = classifier
        self.interval_secs = interval_secs
        self.min_new_traces = min_new_traces
        self._last_trace_count: int = 0
        self._last_failure_count: int = 0
        self._last_learned_at: datetime | None = None
        self._total_learn_calls: int = 0
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background polling loop."""
        if self._running:
            logger.warning("OutcomeTracker already running")
            return
        self._running = True
        self._last_trace_count = await self._count_traces()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "OutcomeTracker started (interval=%ss, min_new=%d, initial_traces=%d)",
            self.interval_secs,
            self.min_new_traces,
            self._last_trace_count,
        )

    async def stop(self) -> None:
        """Stop the background polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("OutcomeTracker stopped (total learn calls: %d)", self._total_learn_calls)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("OutcomeTracker tick failed")
            await asyncio.sleep(self.interval_secs)

    async def _tick(self) -> None:
        current = await self._count_traces()
        new_traces = current - self._last_trace_count
        self._last_trace_count = current

        if new_traces < self.min_new_traces:
            return

        logger.info(
            "OutcomeTracker: %d new traces (total %d), calling transition_model.learn()",
            new_traces,
            current,
        )
        processed = await self.transition_model.learn(self.store)
        self._last_learned_at = datetime.now(timezone.utc)
        self._total_learn_calls += 1
        logger.info(
            "OutcomeTracker: learned from %d traces (total learn calls: %d)",
            processed,
            self._total_learn_calls,
        )

        if self.classifier:
            await self._update_signatures()

    async def _count_traces(self) -> int:
        """Count unique trace IDs in the store."""
        spans = await self.store.query_traces(limit=10000)
        return len({s.trace_id for s in spans})

    async def _update_signatures(self) -> None:
        """Classify new failures and add to SignatureDB as training examples."""
        if not self.classifier:
            return
        failures = await self.store.get_failures(limit=100)
        current = len(failures)
        new_count = current - self._last_failure_count
        self._last_failure_count = current

        if new_count <= 0:
            return

        added = 0
        for f in failures[-new_count:]:
            error_text = f.get("error", "")
            failure_mode_str = f.get("failure_mode", "")
            if not error_text or not failure_mode_str:
                continue
            try:
                from agenticu.models import FailureMode

                FailureMode(failure_mode_str)  # validate; classifier decides the mode
            except ValueError:
                continue

            result = self.classifier.classify(
                Span(status=SpanStatus.ERROR, error_message=error_text),
                trace_text=error_text,
            )
            if result.failure_mode is not None and result.confidence >= 0.8:
                self.classifier.signature_db.add_signature(result.failure_mode, error_text)
                added += 1

        if added:
            logger.info("OutcomeTracker: added %d new signatures to SignatureDB", added)

    @property
    def last_learned_at(self) -> datetime | None:
        return self._last_learned_at

    @property
    def total_learn_calls(self) -> int:
        return self._total_learn_calls

    @property
    def is_running(self) -> bool:
        return self._running
