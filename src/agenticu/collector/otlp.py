"""Translate OTLP trace requests into AgentICU spans."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any

from google.protobuf.json_format import ParseDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.trace.v1.trace_pb2 import Span as OTLPSpan
from opentelemetry.proto.trace.v1.trace_pb2 import Status

from agenticu.models import FailureMode, Span, SpanEvent, SpanStatus

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _json_ids(value: Any) -> None:
    """Translate OTLP/JSON hex IDs to the bytes accepted by protobuf's JSON parser."""
    if isinstance(value, list):
        for child in value:
            _json_ids(child)
    elif isinstance(value, dict):
        for key, child in value.items():
            if key in (
                "traceId",
                "spanId",
                "parentSpanId",
                "trace_id",
                "span_id",
                "parent_span_id",
            ):
                if not isinstance(child, str):
                    raise ValueError(f"{key} must be a hexadecimal string")
                if any(character not in "0123456789abcdefABCDEF" for character in child):
                    raise ValueError(f"{key} must be a hexadecimal string")
                value[key] = base64.b64encode(bytes.fromhex(child)).decode("ascii")
            else:
                _json_ids(child)


def parse_otlp_json(body: Any) -> ExportTraceServiceRequest:
    if not isinstance(body, dict) or not {"resourceSpans", "resource_spans"}.intersection(body):
        raise ValueError("Expected an OTLP object with resourceSpans")
    _json_ids(body)
    return ParseDict(body, ExportTraceServiceRequest(), ignore_unknown_fields=True)


def _value(item: Any) -> Any:
    field = item.WhichOneof("value")
    if field == "array_value":
        return [_value(value) for value in item.array_value.values]
    if field == "kvlist_value":
        return _attributes(item.kvlist_value.values)
    if field == "bytes_value":
        return item.bytes_value.hex()
    if field is None:
        return None
    value = getattr(item, field)
    if field == "double_value" and not float("-inf") < value < float("inf"):
        return str(value)
    return value


def _attributes(items: Any) -> dict[str, Any]:
    return {item.key: _value(item.value) for item in items}


def _timestamp(nanos: int) -> datetime:
    return _EPOCH + timedelta(microseconds=nanos // 1000)


def _span(span: OTLPSpan, resource: dict[str, Any]) -> Span:
    if len(span.trace_id) != 16 or not any(span.trace_id):
        raise ValueError("traceId must be a nonzero 16-byte ID")
    if len(span.span_id) != 8 or not any(span.span_id):
        raise ValueError("spanId must be a nonzero 8-byte ID")
    if span.parent_span_id and (len(span.parent_span_id) != 8 or not any(span.parent_span_id)):
        raise ValueError("parentSpanId must contain 8 bytes when present")
    if not span.name or not span.start_time_unix_nano:
        raise ValueError("Span name and startTimeUnixNano are required")
    if span.end_time_unix_nano < span.start_time_unix_nano:
        raise ValueError("endTimeUnixNano must be at or after startTimeUnixNano")
    attributes = {**resource, **_attributes(span.attributes)}
    attributes["otel.span.name"] = span.name
    events = [
        SpanEvent(item.name, _timestamp(item.time_unix_nano), _attributes(item.attributes))
        for item in span.events
    ]
    exception = next((event for event in events if event.name == "exception"), None)
    error = attributes.get("agenticu.error") or span.status.message
    if not error and exception:
        error = exception.attributes.get("exception.message") or exception.attributes.get(
            "exception.type"
        )
    mode = attributes.get("agenticu.failure_mode")
    try:
        failure_mode = FailureMode(mode)
    except (TypeError, ValueError):
        failure_mode = None
    status = SpanStatus.OK
    if error or failure_mode or exception:
        status = SpanStatus.FAILURE
    elif span.status.code == Status.STATUS_CODE_ERROR:
        status = SpanStatus.ERROR
    return Span(
        trace_id=str(attributes.get("agenticu.trace_id") or span.trace_id.hex()),
        span_id=span.span_id.hex(),
        parent_span_id=span.parent_span_id.hex() or None,
        span_type=str(attributes.get("agenticu.span_type") or "agent"),
        agent_id=str(attributes.get("agenticu.agent_id") or attributes.get("service.name") or ""),
        input=attributes.get("agenticu.input"),
        output=attributes.get("agenticu.output"),
        attributes=attributes,
        events=events,
        start_time=_timestamp(span.start_time_unix_nano),
        end_time=_timestamp(span.end_time_unix_nano),
        status=status,
        failure_mode=failure_mode,
        error_message=str(error) if error else None,
    )


def normalize_otlp(request: ExportTraceServiceRequest) -> list[Span]:
    return [
        _span(span, _attributes(resource.resource.attributes))
        for resource in request.resource_spans
        for scope in resource.scope_spans
        for span in scope.spans
    ]
