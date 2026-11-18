from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from agenticu.models import (
    FAILURE_CATEGORY_MAP,
    FailureMode,
    RecoveryAttempt,
    RecoveryOutcome,
    Span,
    SpanEvent,
    SpanStatus,
)

logger = logging.getLogger(__name__)


class TraceStore:
    """PostgreSQL-backed trace storage.

    Falls back to in-memory dict storage if no connection pool is provided
    (for testing / development without Postgres).

    In-memory mode has a configurable max_traces limit to prevent unbounded
    memory growth. The oldest traces are evicted when the limit is exceeded.
    """

    def __init__(self, pool: Any | None = None, max_traces: int = 1000):
        self._pool = pool
        self._memory: dict[str, list[Span]] = {}
        self._failures: list[dict[str, Any]] = []
        self._recoveries: list[RecoveryAttempt] = []
        self._max_traces = max_traces

    # ------------------------------------------------------------------ #
    # Sync helpers (for OTel exporter sync path)
    # ------------------------------------------------------------------ #

    def _insert_span_sync(self, span: Span) -> None:
        self._memory.setdefault(span.trace_id, []).append(span)
        if len(self._memory) > self._max_traces:
            self._evict_oldest_trace()

    def _record_failure_sync(
        self,
        trace_id: str,
        span_id: str,
        agent_id: str,
        failure_mode: FailureMode,
        error: str,
    ) -> None:
        self._failures.append(
            {
                "trace_id": trace_id,
                "span_id": span_id,
                "agent_id": agent_id,
                "failure_mode": failure_mode.value,
                "error": error,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    # ------------------------------------------------------------------ #
    # Span operations
    # ------------------------------------------------------------------ #

    async def insert_span(self, span: Span) -> None:
        if self._pool:
            await self._pool.execute(_INSERT_SPAN, *_span_parameters(span))
        else:
            self._insert_span_sync(span)

    async def insert_spans(self, spans: list[Span]) -> None:
        if self._pool:
            await self._pool.executemany(_INSERT_SPAN, [_span_parameters(span) for span in spans])
            return
        for span in spans:
            if not any(
                saved.span_id == span.span_id for saved in self._memory.get(span.trace_id, [])
            ):
                self._insert_span_sync(span)

    async def query_traces(
        self,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Span]:
        if self._pool:
            rows = await self._pool.fetch(
                """
                SELECT * FROM spans
                WHERE (CAST($1 AS TEXT) IS NULL OR agent_id = $1)
                  AND (CAST($2 AS TEXT) IS NULL OR status = $2)
                ORDER BY start_time DESC
                LIMIT $3 OFFSET $4
                """,
                agent_id,
                status,
                limit,
                offset,
            )
            return [self._row_to_span(r) for r in rows]
        spans = []
        for s in self._memory.values():
            spans.extend(s)
        if agent_id:
            spans = [s for s in spans if s.agent_id == agent_id]
        if status:
            spans = [s for s in spans if s.status.value == status]
        spans.sort(key=lambda s: s.start_time, reverse=True)
        return spans[offset : offset + limit]

    async def get_trace_by_id(self, trace_id: str) -> list[Span]:
        if self._pool:
            rows = await self._pool.fetch(
                "SELECT * FROM spans WHERE trace_id = $1 ORDER BY start_time ASC",
                trace_id,
            )
            return [self._row_to_span(r) for r in rows]
        return self._memory.get(trace_id, [])

    @staticmethod
    def _row_to_span(row: Any) -> Span:
        return Span(
            span_id=row["id"],
            trace_id=row["trace_id"],
            parent_span_id=row.get("parent_span_id"),
            span_type=row["span_type"],
            agent_id=row["agent_id"],
            input=json.loads(row["input"]) if row.get("input") else None,
            output=json.loads(row["output"]) if row.get("output") else None,
            attributes=json.loads(row["attributes"]) if row.get("attributes") else {},
            start_time=_read_timestamp(row["start_time"]),
            end_time=_read_timestamp(row.get("end_time")),
            events=[
                SpanEvent(
                    event["name"], datetime.fromisoformat(event["timestamp"]), event["attributes"]
                )
                for event in json.loads(row.get("events") or "[]")
            ],
            status=SpanStatus(row["status"]),
            failure_mode=FailureMode(row["failure_mode"]) if row.get("failure_mode") else None,
            error_message=row.get("error_message"),
        )

    def _evict_oldest_trace(self) -> None:
        oldest_tid: str | None = None
        oldest_start = datetime.max.replace(tzinfo=timezone.utc)
        for tid, spans in self._memory.items():
            if not spans:
                continue
            if spans[0].start_time < oldest_start:
                oldest_start = spans[0].start_time
                oldest_tid = tid
        if oldest_tid is not None:
            del self._memory[oldest_tid]

    # ------------------------------------------------------------------ #
    # Failure operations
    # ------------------------------------------------------------------ #

    async def record_failure(
        self,
        trace_id: str,
        span_id: str,
        agent_id: str,
        failure_mode: FailureMode,
        error: str,
        *,
        severity: str = "error",
        timestamp: datetime | None = None,
    ) -> bool:
        category = FAILURE_CATEGORY_MAP[failure_mode].value
        timestamp = timestamp or datetime.now(timezone.utc)
        classification_key = json.dumps([trace_id, span_id])
        if self._pool:
            row = await self._pool.fetchrow(
                """
                INSERT INTO failures (trace_id, span_id, agent_id, failure_mode, error_message,
                                      classification_key, category, severity, timestamp)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (classification_key) DO NOTHING RETURNING id
                """,
                trace_id,
                span_id,
                agent_id,
                failure_mode.value,
                error,
                classification_key,
                category,
                severity,
                timestamp,
            )
            return row is not None
        if any(f["trace_id"] == trace_id and f["span_id"] == span_id for f in self._failures):
            return False
        self._failures.append(
            {
                "trace_id": trace_id,
                "span_id": span_id,
                "agent_id": agent_id,
                "failure_mode": failure_mode.value,
                "error": error,
                "category": category,
                "severity": severity,
                "timestamp": timestamp.isoformat(),
            }
        )
        return True

    async def get_failures(
        self,
        failure_mode: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if self._pool:
            rows = await self._pool.fetch(
                """
                SELECT * FROM failures
                WHERE (CAST($1 AS TEXT) IS NULL OR failure_mode = $1)
                  AND (CAST($2 AS TEXT) IS NULL OR agent_id = $2)
                ORDER BY timestamp DESC
                LIMIT $3
                """,
                failure_mode,
                agent_id,
                limit,
            )
            return [_failure_response(dict(row)) for row in rows]
        results = self._failures
        if failure_mode:
            results = [f for f in results if f["failure_mode"] == failure_mode]
        if agent_id:
            results = [f for f in results if f["agent_id"] == agent_id]
        return [_failure_response(dict(row)) for row in results[:limit]]

    # ------------------------------------------------------------------ #
    # Recovery operations
    # ------------------------------------------------------------------ #

    async def insert_recovery(self, attempt: RecoveryAttempt) -> bool:
        if self._pool:
            row = await self._pool.fetchrow(
                """
                INSERT INTO recovery_attempts (id, trace_id, span_id, failure_mode,
                                               attempt_number, strategy, success, started_at,
                                               completed_at, error_message, outcome, root_agent_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (id) DO NOTHING RETURNING id
                """,
                attempt.attempt_id,
                attempt.trace_id,
                attempt.span_id,
                attempt.failure_mode.value if attempt.failure_mode else None,
                attempt.attempt_number,
                attempt.strategy,
                attempt.success,
                attempt.started_at,
                attempt.completed_at,
                attempt.error_message,
                attempt.outcome.value if attempt.outcome else None,
                attempt.root_agent_id,
            )
            return row is not None
        if any(saved.attempt_id == attempt.attempt_id for saved in self._recoveries):
            return False
        self._recoveries.append(attempt)
        return True

    async def get_recovery_attempts(
        self, trace_id: str | None = None, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        if self._pool:
            rows = await self._pool.fetch(
                """
                SELECT id AS attempt_id, trace_id, span_id, failure_mode, attempt_number, strategy,
                       success, started_at, completed_at, error_message, outcome, root_agent_id
                FROM recovery_attempts
                WHERE CAST($1 AS TEXT) IS NULL OR trace_id = $1
                ORDER BY started_at DESC, attempt_number DESC LIMIT $2
                """,
                trace_id,
                limit,
            )
            records = [dict(row) for row in rows]
            for record in records:
                if record["success"] is not None:
                    record["success"] = bool(record["success"])
                for field in ("started_at", "completed_at"):
                    record[field] = _read_timestamp(record[field])
            return records
        attempts = [
            attempt
            for attempt in self._recoveries
            if trace_id is None or attempt.trace_id == trace_id
        ]
        attempts.sort(
            key=lambda attempt: (attempt.started_at, attempt.attempt_number), reverse=True
        )
        return [asdict(attempt) for attempt in attempts[:limit]]

    async def get_recovery_breakdown(self) -> list[dict[str, Any]]:
        if self._pool:
            rows = await self._pool.fetch(
                """
                SELECT strategy, failure_mode, COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE outcome = 'recovered') AS recovered
                FROM recovery_attempts
                WHERE outcome IN ('recovered', 'retried', 'failed')
                GROUP BY strategy, failure_mode ORDER BY strategy, failure_mode
                """
            )
            groups = [dict(row) for row in rows]
        else:
            counts: dict[tuple[str, str | None], dict[str, Any]] = {}
            for attempt in self._recoveries:
                if attempt.outcome in (None, RecoveryOutcome.ESCALATED):
                    continue
                key = (attempt.strategy, attempt.failure_mode)
                row = counts.setdefault(
                    key, {"strategy": key[0], "failure_mode": key[1], "total": 0, "recovered": 0}
                )
                row["total"] += 1
                row["recovered"] += attempt.outcome == RecoveryOutcome.RECOVERED
            groups = list(counts.values())
        for group in groups:
            group["success_rate"] = group["recovered"] / group["total"]
            group["below_threshold"] = group["success_rate"] < 0.5
        return groups

    async def get_recovery_stats(self) -> dict[str, Any]:
        if self._pool:
            row = await self._pool.fetchrow(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE success = true) AS succeeded,
                    COUNT(*) FILTER (WHERE success = false) AS failed
                FROM recovery_attempts
                WHERE outcome IS NULL OR outcome <> 'escalated'
                """
            )
            return dict(row) if row else {"total": 0, "succeeded": 0, "failed": 0}
        attempts = [r for r in self._recoveries if r.outcome != RecoveryOutcome.ESCALATED]
        succeeded = sum(1 for r in attempts if r.success)
        failed = sum(1 for r in attempts if r.success is False)
        return {"total": len(attempts), "succeeded": succeeded, "failed": failed}


def _read_timestamp(value: datetime | str | None) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else value


_INSERT_SPAN = """
INSERT INTO spans (id, trace_id, parent_span_id, span_type, agent_id,
                   input, output, attributes, start_time, end_time, status,
                   failure_mode, error_message, events)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
ON CONFLICT (id) DO NOTHING
"""


def _span_parameters(span: Span) -> tuple:
    return (
        span.span_id,
        span.trace_id,
        span.parent_span_id,
        span.span_type,
        span.agent_id,
        json.dumps(span.input) if span.input is not None else None,
        json.dumps(span.output) if span.output is not None else None,
        json.dumps(span.attributes),
        span.start_time,
        span.end_time,
        span.status.value,
        span.failure_mode.value if span.failure_mode else None,
        span.error_message,
        json.dumps(
            [
                {
                    "name": event.name,
                    "timestamp": event.timestamp.isoformat(),
                    "attributes": event.attributes,
                }
                for event in span.events
            ]
        ),
    )


def _failure_response(row: dict[str, Any]) -> dict[str, Any]:
    row.pop("classification_key", None)
    row["error"] = row.get("error", row.get("error_message"))
    if not row.get("category"):
        try:
            row["category"] = FAILURE_CATEGORY_MAP[FailureMode(row["failure_mode"])].value
        except (KeyError, ValueError):
            row["category"] = None
    row["severity"] = row.get("severity") or "error"
    return row
