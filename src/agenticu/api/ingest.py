"""HTTP trace collection endpoints."""

from __future__ import annotations

import gzip
import json
import zlib
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from google.protobuf.json_format import ParseError
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from agenticu.collector.otlp import normalize_otlp, parse_otlp_json
from agenticu.models import FailureMode, Span, SpanStatus


class DebugSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1)
    span_id: str = Field(min_length=1)
    parent_span_id: str | None = None
    agent_id: str = ""
    span_type: str = "agent"
    input: JsonValue = None
    output: JsonValue = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    start_time: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: AwareDatetime | None = None
    status: SpanStatus = SpanStatus.OK
    failure_mode: FailureMode | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_times(self) -> DebugSpan:
        if self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("end_time must be at or after start_time")
        json.dumps((self.input, self.output, self.attributes), allow_nan=False)
        return self

    def to_span(self) -> Span:
        data = self.model_dump()
        for field in ("start_time", "end_time"):
            if data[field] is not None:
                data[field] = data[field].astimezone(timezone.utc)
        return Span(**data)


class DebugBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spans: list[DebugSpan] = Field(min_length=1)


def _reject_constant(value: str) -> Any:
    raise ValueError(f"Invalid JSON constant {value}")


def register_ingestion(app: FastAPI, ingest: Callable[[list[Span]], Awaitable[None]]) -> None:
    @app.post("/ingest")
    async def debug_ingest(payload: DebugBatch):
        await ingest([item.to_span() for item in payload.spans])
        return {"accepted": len(payload.spans)}

    @app.post("/v1/traces")
    async def otlp_ingest(request: Request):
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type not in ("application/x-protobuf", "application/json"):
            raise HTTPException(415, "Use application/x-protobuf or application/json for OTLP")
        encoding = request.headers.get("content-encoding", "identity").strip().lower()
        if encoding not in ("identity", "gzip"):
            raise HTTPException(415, "Use identity or gzip content encoding for OTLP")
        try:
            body = await request.body()
            if encoding == "gzip":
                body = gzip.decompress(body)
            if media_type == "application/json":
                message = parse_otlp_json(json.loads(body, parse_constant=_reject_constant))
            else:
                message = ExportTraceServiceRequest.FromString(body)
            spans = normalize_otlp(message)
        except (
            DecodeError,
            ParseError,
            ValueError,
            OverflowError,
            OSError,
            EOFError,
            zlib.error,
        ) as exc:
            raise HTTPException(400, f"Invalid OTLP trace payload: {exc}") from exc

        if spans:
            await ingest(spans)
        if media_type == "application/x-protobuf":
            # An empty ExportTraceServiceResponse serializes to zero bytes.
            return Response(content=b"", media_type=media_type)
        return {}
