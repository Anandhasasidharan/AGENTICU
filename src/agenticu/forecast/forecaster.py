from __future__ import annotations

import logging

from agenticu.collector.storage import TraceStore
from agenticu.forecast.transition_model import TransitionModel
from agenticu.models import ForecastResult

logger = logging.getLogger(__name__)


class Forecaster:
    """Real-time failure forecaster for multi-agent handoffs.

    Uses a TransitionModel to predict failure probability at each handoff
    point. When the probability exceeds a threshold, emits a high-severity
    ForecastResult.

    Usage:
        model = TransitionModel()
        await model.learn(store)
        forecaster = Forecaster(model, threshold=0.3)
        result = await forecaster.forecast_at_handoff("agent_a", "agent_b")
    """

    def __init__(
        self,
        model: TransitionModel,
        threshold: float = 0.3,
    ):
        self._model = model
        self.threshold = threshold

    async def forecast_at_handoff(
        self,
        source_agent: str,
        target_agent: str,
    ) -> ForecastResult:
        """Predict failure probability for an imminent handoff.

        Args:
            source_agent: The agent initiating the handoff.
            target_agent: The agent receiving control.

        Returns:
            ForecastResult with probability, predicted mode, and confidence.
        """
        prob, mode, confidence, samples = self._model.predict(source_agent, target_agent)

        return ForecastResult(
            failure_probability=prob,
            predicted_mode=mode,
            confidence=confidence,
            source_agent=source_agent,
            target_agent=target_agent,
            threshold_exceeded=prob >= self.threshold,
            samples_seen=samples,
        )

    async def forecast_trace(
        self,
        trace_id: str,
        store: TraceStore,
    ) -> list[ForecastResult]:
        """Forecast failure probability at every handoff in a trace.

        Useful for offline analysis of a completed or in-progress trace.
        """
        spans = await store.get_trace_by_id(trace_id)
        results: list[ForecastResult] = []
        for s in spans:
            if s.span_type == "handoff":
                source = s.agent_id or ""
                target = s.attributes.get("agenticu.target_agent", "") if s.attributes else ""
                if source and target:
                    result = await self.forecast_at_handoff(source, target)
                    results.append(result)
        return results
