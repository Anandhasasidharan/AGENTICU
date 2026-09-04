from __future__ import annotations

from collections import defaultdict

from agenticu.collector.storage import TraceStore
from agenticu.models import FailureMode, Span


class TransitionModel:
    """Markov transition model for multi-agent handoff dynamics.

    Learns P(failure | source_agent, target_agent) from completed traces.
    State representation:
      - source_agent, target_agent at each handoff
      - outcome: which failure mode occurred (or None for success)

    The model is a simple counting estimator:
      P(failure | src, tgt) = count(src->tgt with failure) / count(src->tgt)
    """

    def __init__(self):
        self._handoff_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._failure_counts: dict[tuple[str, str], dict[FailureMode, int]] = defaultdict(
            lambda: defaultdict(int)
        )

    async def learn(self, store: TraceStore) -> int:
        """Rebuild the transition matrix from all stored traces.

        Returns the number of traces processed.
        """
        self._handoff_counts.clear()
        self._failure_counts.clear()

        seen_trace_ids: set[str] = set()
        spans = await store.query_traces(limit=5000)
        for span in spans:
            seen_trace_ids.add(span.trace_id)

        processed = 0
        for trace_id in seen_trace_ids:
            trace_spans = await store.get_trace_by_id(trace_id)
            self._learn_from_trace(trace_spans)
            processed += 1

        return processed

    def _learn_from_trace(self, spans: list[Span]) -> None:
        sorted_spans = sorted(spans, key=lambda s: s.start_time)

        last_handoff: tuple[str, str, int] | None = None
        for s in sorted_spans:
            if s.span_type == "handoff":
                src = s.agent_id or ""
                tgt = s.attributes.get("agenticu.target_agent", "") if s.attributes else ""
                if src and tgt:
                    last_handoff = (src, tgt)
                    key = (src, tgt)
                    self._handoff_counts[key] += 1

            if s.failure_mode is not None and last_handoff is not None:
                src, tgt = last_handoff[0], last_handoff[1]
                key = (src, tgt)
                self._failure_counts[key][s.failure_mode] += 1

    def predict(
        self, source_agent: str, target_agent: str
    ) -> tuple[float, FailureMode | None, float, int]:
        """Predict P(failure | source_agent -> target_agent).

        Returns (probability, most_likely_mode, confidence, samples_seen).
        """
        key = (source_agent, target_agent)
        total = self._handoff_counts.get(key, 0)
        if total == 0:
            return (0.0, None, 0.0, 0)

        best_mode: FailureMode | None = None
        best_count = 0
        total_failures = 0
        for mode, cnt in self._failure_counts[key].items():
            total_failures += cnt
            if cnt > best_count:
                best_count = cnt
                best_mode = mode

        prob = total_failures / total
        confidence = min(total / 10.0, 1.0)
        return (prob, best_mode, confidence, total)

    @property
    def known_transitions(self) -> list[tuple[str, str]]:
        return list(self._handoff_counts.keys())
