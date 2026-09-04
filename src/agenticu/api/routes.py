from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest
from pydantic import BaseModel
from starlette.status import HTTP_403_FORBIDDEN

from agenticu.attribution.causal_attributor import CausalAttributor
from agenticu.collector.storage import TraceStore
from agenticu.forecast.forecaster import Forecaster
from agenticu.forecast.outcome_tracker import OutcomeTracker
from agenticu.models import FAILURE_CATEGORY_MAP, FailureMode, Span
from agenticu.recovery.playbook_runner import PlaybookRunner
from agenticu.recovery.recovery_metrics import MetricsTracker


class RecoverRequest(BaseModel):
    trace_id: str
    failure_mode: str


def _api_key_middleware(api_key: str):
    async def middleware(request: Request, call_next: Any) -> Any:
        if request.url.path in ("/health", "/metrics"):
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {api_key}":
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "Forbidden"}, status_code=HTTP_403_FORBIDDEN)
        return await call_next(request)

    return middleware


def create_app(
    store: TraceStore,
    runner: PlaybookRunner,
    metrics: MetricsTracker,
    cors_origins: list[str] | None = None,
    api_key: str = "",
    attributor: CausalAttributor | None = None,
    forecaster: Forecaster | None = None,
    outcome_tracker: OutcomeTracker | None = None,
) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if outcome_tracker:
            await outcome_tracker.start()
        yield
        if outcome_tracker:
            await outcome_tracker.stop()

    app = FastAPI(title="AgentICU", version="0.1.0", lifespan=lifespan)

    origins = cors_origins or ["http://localhost:3000"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    if api_key:
        app.middleware("http")(_api_key_middleware(api_key))

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics_endpoint():
        return generate_latest()

    @app.get("/api/v1/traces")
    async def list_traces(
        agent_id: str | None = Query(None),
        status: str | None = Query(None),
        limit: int = Query(100, le=500),
        offset: int = Query(0, ge=0),
    ):
        spans = await store.query_traces(
            agent_id=agent_id, status=status, limit=limit, offset=offset
        )
        return _spans_to_response(spans)

    @app.get("/api/v1/traces/{trace_id}")
    async def get_trace(trace_id: str):
        spans = await store.get_trace_by_id(trace_id)
        if not spans:
            raise HTTPException(404, "Trace not found")
        return _spans_to_response(spans)

    @app.get("/api/v1/failures")
    async def list_failures(
        failure_mode: str | None = Query(None),
        agent_id: str | None = Query(None),
        limit: int = Query(100, le=500),
    ):
        failures = await store.get_failures(
            failure_mode=failure_mode, agent_id=agent_id, limit=limit
        )
        return {"failures": failures}

    @app.post("/api/v1/recover")
    async def trigger_recovery(req: RecoverRequest):
        try:
            mode = FailureMode(req.failure_mode)
        except ValueError:
            raise HTTPException(400, f"Invalid failure mode: {req.failure_mode}")
        spans = await store.get_trace_by_id(req.trace_id)
        if not spans:
            raise HTTPException(404, "Trace not found")
        last_span = spans[-1]
        attempt = await runner.run(last_span, mode)
        return {
            "attempt_id": attempt.attempt_id,
            "success": attempt.success,
            "strategy": attempt.strategy,
            "error": attempt.error_message,
        }

    @app.get("/api/v1/metrics/recovery")
    async def recovery_metrics():
        stats = await store.get_recovery_stats()
        return {
            "total": stats["total"],
            "succeeded": stats["succeeded"],
            "failed": stats["failed"],
            "success_rate": stats["succeeded"] / stats["total"] if stats["total"] > 0 else 0.0,
            "by_mode": metrics.count_by_mode(),
        }

    if attributor is not None:

        @app.get("/api/v1/attribution")
        async def get_attribution(
            trace_id: str = Query(...),
            span_id: str = Query(...),
        ):
            result = await attributor.attribute(trace_id, span_id)
            return {
                "root_agent_id": result.root_agent_id,
                "confidence": result.confidence,
                "attribution_chain": result.attribution_chain,
                "failure_span_id": result.failure_span_id,
                "root_cause_description": result.root_cause_description,
            }

    if forecaster is not None:

        @app.get("/api/v1/forecast")
        async def get_forecast(
            source_agent: str = Query(...),
            target_agent: str = Query(...),
        ):
            result = await forecaster.forecast_at_handoff(source_agent, target_agent)
            return {
                "failure_probability": result.failure_probability,
                "predicted_mode": result.predicted_mode.value if result.predicted_mode else None,
                "confidence": result.confidence,
                "source_agent": result.source_agent,
                "target_agent": result.target_agent,
                "threshold_exceeded": result.threshold_exceeded,
                "samples_seen": result.samples_seen,
            }

        @app.get("/api/v1/forecast/trace")
        async def get_forecast_trace(
            trace_id: str = Query(...),
        ):
            results = await forecaster.forecast_trace(trace_id, store)
            return {
                "forecasts": [
                    {
                        "failure_probability": r.failure_probability,
                        "predicted_mode": r.predicted_mode.value if r.predicted_mode else None,
                        "confidence": r.confidence,
                        "source_agent": r.source_agent,
                        "target_agent": r.target_agent,
                        "threshold_exceeded": r.threshold_exceeded,
                        "samples_seen": r.samples_seen,
                    }
                    for r in results
                ]
            }

    if outcome_tracker is not None:

        @app.get("/api/v1/outcome-tracker")
        async def outcome_tracker_status():
            return {
                "is_running": outcome_tracker.is_running,
                "total_learn_calls": outcome_tracker.total_learn_calls,
                "last_learned_at": outcome_tracker.last_learned_at.isoformat()
                if outcome_tracker.last_learned_at
                else None,
            }

    return app


def _spans_to_response(spans: list[Span]) -> dict[str, Any]:
    return {
        "spans": [
            {
                "span_id": s.span_id,
                "trace_id": s.trace_id,
                "span_type": s.span_type,
                "agent_id": s.agent_id,
                "status": s.status.value,
                "failure_mode": s.failure_mode.value if s.failure_mode else None,
                "category": (
                    FAILURE_CATEGORY_MAP[s.failure_mode].value if s.failure_mode else None
                ),
                "error": s.error_message,
                "start_time": s.start_time.isoformat(),
                "end_time": s.end_time.isoformat() if s.end_time else None,
            }
            for s in spans
        ]
    }
