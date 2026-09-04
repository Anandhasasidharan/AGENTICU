from __future__ import annotations

from agenticu.models import Span, SpanStatus


class TraceProcessor:
    """Dedup, enrich, and validate spans before storage."""

    def __init__(self) -> None:
        self._seen_span_ids: set[str] = set()

    def process(self, span: Span) -> Span:
        if span.span_id in self._seen_span_ids:
            raise ValueError(f"Duplicate span_id: {span.span_id}")
        self._seen_span_ids.add(span.span_id)

        if span.status == SpanStatus.ERROR and not span.error_message:
            span.error_message = "No error message captured"

        return span

    def clear(self) -> None:
        self._seen_span_ids.clear()
