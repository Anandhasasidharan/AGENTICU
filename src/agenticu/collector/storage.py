from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from agenticu.models import FailureMode, RecoveryAttempt, Span, SpanStatus

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
            await self._pool.execute(
                """
                INSERT INTO spans (id, trace_id, parent_span_id, span_type, agent_id,
                                   input, output, attributes, start_time,
                                   end_time, status, failure_mode, error_message)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                ON CONFLICT (id) DO NOTHING
                """,
                span.span_id,
                span.trace_id,
                span.parent_span_id,
                span.span_type,
                span.agent_id,
                json.dumps(span.input) if span.input else None,
                json.dumps(span.output) if span.output else None,
                json.dumps(span.attributes),
                span.start_time,
                span.end_time,
                span.status.value,
                span.failure_mode.value if span.failure_mode else None,
                span.error_message,
            )
            return
        self._memory.setdefault(span.trace_id, []).append(span)
        if len(self._memory) > self._max_traces:
            self._evict_oldest_trace()

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
                WHERE ($1::text IS NULL OR agent_id = $1)
                  AND ($2::text IS NULL OR status = $2)
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
        return spans[:limit]

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
            start_time=row["start_time"],
            end_time=row.get("end_time"),
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
    ) -> None:
        if self._pool:
            await self._pool.execute(
                """
                INSERT INTO failures (trace_id, span_id, agent_id, failure_mode, error_message)
                VALUES ($1, $2, $3, $4, $5)
                """,
                trace_id,
                span_id,
                agent_id,
                failure_mode.value,
                error,
            )
            return
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
                WHERE ($1::text IS NULL OR failure_mode = $1)
                  AND ($2::text IS NULL OR agent_id = $2)
                ORDER BY timestamp DESC
                LIMIT $3
                """,
                failure_mode,
                agent_id,
                limit,
            )
            return [dict(r) for r in rows]
        results = self._failures
        if failure_mode:
            results = [f for f in results if f["failure_mode"] == failure_mode]
        if agent_id:
            results = [f for f in results if f["agent_id"] == agent_id]
        return results[:limit]

    # ------------------------------------------------------------------ #
    # Recovery operations
    # ------------------------------------------------------------------ #

    async def insert_recovery(self, attempt: RecoveryAttempt) -> None:
        if self._pool:
            await self._pool.execute(
                """
                INSERT INTO recovery_attempts (id, trace_id, span_id, failure_mode,
                                               attempt_number, strategy, success,
                                               started_at, completed_at, error_message)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
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
            )
            return
        self._recoveries.append(attempt)

    async def get_recovery_stats(self) -> dict[str, Any]:
        if self._pool:
            row = await self._pool.fetchrow(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE success = true) AS succeeded,
                    COUNT(*) FILTER (WHERE success = false) AS failed
                FROM recovery_attempts
                """
            )
            return dict(row) if row else {"total": 0, "succeeded": 0, "failed": 0}
        total = len(self._recoveries)
        succeeded = sum(1 for r in self._recoveries if r.success)
        return {"total": total, "succeeded": succeeded, "failed": total - succeeded}
