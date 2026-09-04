from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from agenticu.collector.storage import TraceStore
from agenticu.models import AttributionResult, Span

logger = logging.getLogger(__name__)


class CausalAttributor:
    """Trace failures back through the handoff/decision chain to the root-cause agent.

    When a failure is detected, walks the trace backwards via parent_span_id
    through handoff and decision spans. The root cause is the agent whose action
    introduced the condition that led to the failure — either:
      - A decision with error/failure language in its rationale
      - A handoff that passed a degraded state snapshot
      - The agent that made the latest handoff before the failure (fallback)

    Usage:
        attributor = CausalAttributor(store)
        result = await attributor.attribute(trace_id, failure_span_id)
    """

    def __init__(self, store: TraceStore):
        self.store = store

    async def attribute(
        self,
        trace_id: str,
        failure_span_id: str,
    ) -> AttributionResult:
        spans = await self.store.get_trace_by_id(trace_id)
        span_map: dict[str, Span] = {s.span_id: s for s in spans}

        failure_span = span_map.get(failure_span_id)
        if failure_span is None:
            return AttributionResult(
                confidence=0.0,
                root_cause_description=f"Span {failure_span_id} not found in trace {trace_id}",
            )

        # Prefer the parent chain when it connects multiple spans; otherwise
        # fall back to chronological order (traces are time-ordered).
        parent_chain = self._walk_parent_chain(failure_span, span_map)
        chrono_chain = sorted(
            spans, key=lambda s: s.start_time or datetime.min.replace(tzinfo=timezone.utc)
        )
        chain = parent_chain if len(parent_chain) > len(chrono_chain) else chrono_chain

        agent_sequence = self._build_agent_sequence(chain)
        root = self._find_root_cause(chain, agent_sequence, failure_span)

        return AttributionResult(
            root_agent_id=root["agent_id"],
            confidence=root["confidence"],
            attribution_chain=agent_sequence,
            failure_span_id=failure_span_id,
            root_cause_description=root["description"],
        )

    @staticmethod
    def _walk_parent_chain(
        span: Span,
        span_map: dict[str, Span],
    ) -> list[Span]:
        chain: list[Span] = []
        current: Span | None = span
        while current is not None:
            chain.append(current)
            if current.parent_span_id and current.parent_span_id in span_map:
                current = span_map[current.parent_span_id]
            else:
                break
        chain.reverse()
        return chain

    @staticmethod
    def _build_agent_sequence(chain: list[Span]) -> list[str]:
        seen: list[str] = []
        for s in chain:
            aid = s.agent_id or ""
            if aid and (not seen or seen[-1] != aid):
                seen.append(aid)
        return seen

    @staticmethod
    def _find_root_cause(
        chain: list[Span],
        agent_sequence: list[str],
        failure_span: Span,
    ) -> dict[str, Any]:
        if len(agent_sequence) < 2:
            return {
                "agent_id": failure_span.agent_id,
                "confidence": 0.9,
                "description": f"Agent '{failure_span.agent_id}' encountered failure directly — "
                f"no handoff chain to trace back through",
            }

        # Walk forward through time. The root cause is the first span (other than
        # the failure span itself) that introduces an error signal.
        for span in chain:
            if span.span_id == failure_span.span_id:
                continue
            txt = _span_text(span)
            if not txt:
                continue
            if _suggests_error(txt):
                if span.span_type == "decision":
                    return {
                        "agent_id": span.agent_id,
                        "confidence": 0.85,
                        "description": (
                            f"Agent '{span.agent_id}' made a decision with error indicators: "
                            f"'{txt[:120]}'"
                        ),
                    }
                if span.span_type == "handoff":
                    return {
                        "agent_id": span.agent_id,
                        "confidence": 0.85,
                        "description": (
                            f"Agent '{span.agent_id}' handed off a degraded state: '{txt[:120]}'"
                        ),
                    }
                return {
                    "agent_id": span.agent_id,
                    "confidence": 0.8,
                    "description": (
                        f"Agent '{span.agent_id}' introduced the error condition: '{txt[:120]}'"
                    ),
                }

        # No error signal found in preceding spans — attribute to last handoff source
        last_handoff = next(
            (
                s
                for s in reversed(chain)
                if s.span_type == "handoff" and s.span_id != failure_span.span_id
            ),
            None,
        )
        if last_handoff:
            return {
                "agent_id": last_handoff.agent_id,
                "confidence": 0.6,
                "description": (
                    f"Agent '{last_handoff.agent_id}' initiated the last handoff "
                    f"before failure; no error signal found in handoff state"
                ),
            }

        return {
            "agent_id": agent_sequence[-2] if len(agent_sequence) >= 2 else failure_span.agent_id,
            "confidence": 0.5,
            "description": "No clear root cause found; attributed to preceding agent",
        }


def _span_text(span: Span) -> str:
    parts: list[str] = []
    if span.output:
        parts.append(str(span.output))
    if span.input:
        parts.append(str(span.input))
    if span.error_message:
        parts.append(span.error_message)
    return " ".join(parts)


def _suggests_error(text: str) -> bool:
    lowered = text.lower()
    keywords = [
        "error",
        "fail",
        "exception",
        "timeout",
        "invalid",
        "unexpected",
        "incorrect",
        "wrong",
        "missing",
        "bad",
        "corrupt",
        "degraded",
    ]
    return any(kw in lowered for kw in keywords)
