"""SDK span exporter for a remote AgentICU collector."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from opentelemetry import trace
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

logger = logging.getLogger(__name__)
_setup_lock = threading.Lock()
_configured_provider: TracerProvider | None = None


def _value(value: Any) -> AnyValue:
    if isinstance(value, bool):
        return AnyValue(bool_value=value)
    if isinstance(value, str):
        return AnyValue(string_value=value)
    if isinstance(value, int) and -(2**63) <= value < 2**63:
        return AnyValue(int_value=value)
    if isinstance(value, float):
        return AnyValue(double_value=value)
    if isinstance(value, bytes):
        return AnyValue(bytes_value=value)
    if isinstance(value, (list, tuple)):
        result = AnyValue()
        result.array_value.values.extend(_value(item) for item in value)
        return result
    return AnyValue(string_value=str(value))


def _attributes(attributes: Mapping[str, Any] | None) -> list[KeyValue]:
    return [KeyValue(key=key, value=_value(value)) for key, value in (attributes or {}).items()]


def _request(spans: Sequence[ReadableSpan]) -> ExportTraceServiceRequest:
    request = ExportTraceServiceRequest()
    for item in spans:
        ctx = item.get_span_context()
        if ctx is None or not ctx.is_valid:
            continue
        resource = request.resource_spans.add()
        resource.resource.attributes.extend(_attributes(item.resource.attributes))
        scope = resource.scope_spans.add()
        if item.instrumentation_scope:
            scope.scope.name = item.instrumentation_scope.name
            scope.scope.version = item.instrumentation_scope.version or ""
        span = scope.spans.add(
            name=item.name,
            trace_id=ctx.trace_id.to_bytes(16, "big"),
            span_id=ctx.span_id.to_bytes(8, "big"),
            parent_span_id=item.parent.span_id.to_bytes(8, "big") if item.parent else b"",
            kind=item.kind.value + 1,
            start_time_unix_nano=item.start_time,
            end_time_unix_nano=item.end_time,
            flags=int(ctx.trace_flags),
            attributes=_attributes(item.attributes),
        )
        span.status.code = item.status.status_code.value
        span.status.message = item.status.description or ""
        for event in item.events:
            span.events.add(
                name=event.name,
                time_unix_nano=event.timestamp,
                attributes=_attributes(event.attributes),
            )
        for link in item.links:
            span.links.add(
                trace_id=link.context.trace_id.to_bytes(16, "big"),
                span_id=link.context.span_id.to_bytes(8, "big"),
                attributes=_attributes(link.attributes),
            )
    return request


class AgentICUHTTPExporter(SpanExporter):
    """Send protobuf OTLP batches to an AgentICU server base URL."""

    def __init__(self, server_url: str, api_key: str = "", timeout: float = 10.0):
        url = httpx.URL(server_url)
        if url.scheme not in ("http", "https") or not url.host or url.query or url.fragment:
            raise ValueError("AgentICU server URL must be an HTTP(S) base URL")
        self.endpoint = server_url.rstrip("/") + "/v1/traces"
        headers = {"Content-Type": "application/x-protobuf"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(headers=headers, timeout=timeout)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            response = self._client.post(self.endpoint, content=_request(spans).SerializeToString())
            response.raise_for_status()
        except (httpx.HTTPError, TypeError, ValueError, OverflowError):
            logger.exception("Could not send spans to AgentICU")
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        self._client.close()


def configure_http_export_from_env() -> None:
    """Register a processor once when AGENTICU_SERVER_URL is configured."""
    global _configured_provider

    server_url = os.environ.get("AGENTICU_SERVER_URL")
    if not server_url or _configured_provider is not None:
        return
    with _setup_lock:
        if _configured_provider is not None:
            return
        provider = trace.get_tracer_provider()
        if isinstance(provider, trace.ProxyTracerProvider):
            trace.set_tracer_provider(TracerProvider())
            provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            raise RuntimeError("Configure AgentICUHTTPExporter on your custom tracer provider")
        exporter = AgentICUHTTPExporter(server_url, os.environ.get("AGENTICU__API__KEY", ""))
        provider.add_span_processor(BatchSpanProcessor(exporter))
        _configured_provider = provider
