from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from agenticu import metrics as prom
from agenticu.collector.processor import TraceProcessor
from agenticu.collector.storage import TraceStore
from agenticu.models import FailureMode, SpanStatus
from agenticu.models import Span as AgentICUSpan

logger = logging.getLogger(__name__)


class AgentICUExporter(SpanExporter):
    def __init__(self, store: TraceStore, processor: TraceProcessor | None = None):
        self.store = store
        self.processor = processor or TraceProcessor()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for otel_span in spans:
            try:
                span = self._convert(otel_span)
                span = self.processor.process(span)
                self.store._insert_span_sync(span)
                prom.record_span(span.agent_id, span.span_type)

                if span.status == SpanStatus.FAILURE and span.failure_mode:
                    self.store._record_failure_sync(
                        trace_id=span.trace_id,
                        span_id=span.span_id,
                        agent_id=span.agent_id,
                        failure_mode=span.failure_mode,
                        error=span.error_message or "unknown",
                    )
                    prom.record_failure(span.failure_mode, span.agent_id)
            except Exception:
                logger.exception("Failed to export span %s", otel_span.get_span_context().span_id)
        return SpanExportResult.SUCCESS

    def _convert(self, otel_span: ReadableSpan) -> AgentICUSpan:
        ctx = otel_span.get_span_context()
        attrs: dict[str, Any] = dict(otel_span.attributes or {})

        span_type = attrs.get("agenticu.span_type", "agent")
        agent_id = attrs.get("agenticu.agent_id", "")
        error = attrs.get("agenticu.error")
        failure_mode_str = attrs.get("agenticu.failure_mode")

        status = SpanStatus.OK
        if otel_span.status and otel_span.status.is_ok is False:
            status = SpanStatus.ERROR
        if error:
            status = SpanStatus.FAILURE

        failure_mode: FailureMode | None = None
        if failure_mode_str is not None:
            try:
                failure_mode = FailureMode(failure_mode_str)
            except ValueError:
                pass

        # Prefer our propagated trace_id attribute (correctly nested across
        # agent handoffs) over the raw OTel context trace_id.
        trace_id = attrs.get("agenticu.trace_id") or hex(ctx.trace_id)[2:]
        parent_otel = otel_span.parent
        parent_span_id = hex(parent_otel.span_id)[2:] if parent_otel else None

        return AgentICUSpan(
            span_id=hex(ctx.span_id)[2:],
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            span_type=span_type,
            agent_id=agent_id,
            input=attrs.get("agenticu.input"),
            output=attrs.get("agenticu.output"),
            attributes=attrs,
            start_time=self._ns_to_dt(otel_span.start_time),
            end_time=self._ns_to_dt(otel_span.end_time),
            status=status,
            failure_mode=failure_mode,
            error_message=error,
        )

    @staticmethod
    def _ns_to_dt(ns: int | None) -> datetime | None:
        if ns is None:
            return None
        if isinstance(ns, datetime):
            return ns
        return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc)

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True
