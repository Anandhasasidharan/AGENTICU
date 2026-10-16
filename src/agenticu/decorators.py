from __future__ import annotations

import asyncio
import functools
import inspect
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from opentelemetry import trace as otel_trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from agenticu import metrics as prom
from agenticu.attribution.causal_attributor import CausalAttributor
from agenticu.classification.classifier import Classifier
from agenticu.collector.storage import TraceStore
from agenticu.context import ContextScope, get_context
from agenticu.models import (
    AgentContext,
    FailureMode,
    RecoveryAction,
    RecoveryAttempt,
    Span,
    SpanStatus,
)
from agenticu.recovery.playbook_registry import get_playbook

F = TypeVar("F", bound=Callable[..., Any])
TRACER = otel_trace.get_tracer("agenticu")


def _get_otel_attributes(ctx: AgentContext, span_type: str, **extra: Any) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "agenticu.trace_id": ctx.trace_id,
        "agenticu.agent_id": ctx.agent_id,
        "agenticu.span_type": span_type,
    }
    if ctx.task_spec:
        attrs["agenticu.task_spec"] = ctx.task_spec
    attrs.update(ctx.attributes)
    attrs.update(extra)
    return attrs


def _capture_input(func: Callable, args: Any, kwargs: Any) -> dict[str, Any]:
    sig = inspect.signature(func)
    bound = sig.bind(*args, **kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


def trace(
    *,
    agent_id: str = "",
    span_name: str | None = None,
    record_input: bool = True,
    record_output: bool = True,
    classifier: Classifier | None = None,
    store: TraceStore | None = None,
    attributor: CausalAttributor | None = None,
    max_retries: int = 1,
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = get_context() or AgentContext(agent_id=agent_id)
            name = span_name or func.__name__

            span_ctx = AgentContext(
                trace_id=ctx.trace_id,
                parent_span_id=ctx.span_id,
                agent_id=agent_id or ctx.agent_id,
            )

            with ContextScope(span_ctx):
                otel_attrs = _get_otel_attributes(span_ctx, "agent")
                if record_input:
                    otel_attrs["agenticu.input"] = str(_capture_input(func, args, kwargs))

                with TRACER.start_as_current_span(
                    name,
                    kind=SpanKind.INTERNAL,
                    attributes=otel_attrs,
                ) as otel_span:
                    try:
                        result = func(*args, **kwargs)
                        if record_output:
                            otel_span.set_attribute("agenticu.output", str(result)[:2000])
                        otel_span.set_status(Status(StatusCode.OK))
                        span_ctx.span_id = format(otel_span.get_span_context().span_id, "x")
                        return result
                    except BaseException as e:
                        otel_span.set_attribute("agenticu.error", str(e))
                        otel_span.set_attribute("agenticu.traceback", traceback.format_exc())
                        otel_span.set_status(Status(StatusCode.ERROR, str(e)))
                        span_ctx.span_id = format(otel_span.get_span_context().span_id, "x")
                        if classifier and store:
                            recovered = _try_inline_recovery(
                                func,
                                args,
                                kwargs,
                                span_ctx,
                                e,
                                record_output,
                                name,
                                classifier,
                                store,
                                attributor,
                                max_retries,
                            )
                            if recovered is not None:
                                return recovered
                        raise

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = get_context() or AgentContext(agent_id=agent_id)
            name = span_name or func.__name__

            span_ctx = AgentContext(
                trace_id=ctx.trace_id,
                parent_span_id=ctx.span_id,
                agent_id=agent_id or ctx.agent_id,
            )

            with ContextScope(span_ctx):
                otel_attrs = _get_otel_attributes(span_ctx, "agent")
                if record_input:
                    otel_attrs["agenticu.input"] = str(_capture_input(func, args, kwargs))

                with TRACER.start_as_current_span(
                    name,
                    kind=SpanKind.INTERNAL,
                    attributes=otel_attrs,
                ) as otel_span:
                    try:
                        result = await func(*args, **kwargs)
                        if record_output:
                            otel_span.set_attribute("agenticu.output", str(result)[:2000])
                        otel_span.set_status(Status(StatusCode.OK))
                        span_ctx.span_id = format(otel_span.get_span_context().span_id, "x")
                        return result
                    except BaseException as e:
                        otel_span.set_attribute("agenticu.error", str(e))
                        otel_span.set_attribute("agenticu.traceback", traceback.format_exc())
                        otel_span.set_status(Status(StatusCode.ERROR, str(e)))
                        span_ctx.span_id = format(otel_span.get_span_context().span_id, "x")
                        if classifier and store:
                            recovered = await _try_inline_recovery_async(
                                func,
                                args,
                                kwargs,
                                span_ctx,
                                e,
                                record_output,
                                name,
                                classifier,
                                store,
                                attributor,
                                max_retries,
                            )
                            if recovered is not None:
                                return recovered
                        raise

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


async def _run_playbook(
    *,
    playbook: Any,
    span_ctx: AgentContext,
    error: BaseException,
    failure_mode: FailureMode,
    store: TraceStore,
    attributor: CausalAttributor | None,
    attempt_number: int,
) -> RecoveryAction:
    """Attribute the failure, run the playbook, and persist the attempt."""
    root_agent_id: str | None = None
    if attributor and span_ctx.trace_id and span_ctx.span_id:
        try:
            attr_result = await attributor.attribute(span_ctx.trace_id, span_ctx.span_id)
            root_agent_id = attr_result.root_agent_id
        except Exception:
            pass

    action = await playbook(
        span=Span(
            trace_id=span_ctx.trace_id,
            span_id=span_ctx.span_id or "",
            agent_id=span_ctx.agent_id,
            status=SpanStatus.ERROR,
            error_message=str(error),
            failure_mode=failure_mode,
        ),
        store=store,
        root_agent_id=root_agent_id,
    )
    await store.insert_recovery(
        RecoveryAttempt(
            trace_id=span_ctx.trace_id,
            span_id=span_ctx.span_id or "",
            failure_mode=failure_mode,
            attempt_number=attempt_number,
            strategy=playbook.__name__,
            root_agent_id=root_agent_id,
            success=action.should_retry,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
    )
    prom.record_recovery(failure_mode, playbook.__name__, action.should_retry)
    return action


def _prepare_inline_recovery(
    error: BaseException,
    classifier: Classifier,
) -> tuple[Any, FailureMode] | None:
    """Classify the failure and look up its playbook, or None if there is nothing to do."""
    trace_text = f"Error: {error}\n{traceback.format_exc()}"
    failure_span = Span(status=SpanStatus.ERROR, error_message=str(error))
    result = classifier.classify(failure_span, trace_text=trace_text)
    if result.failure_mode is None:
        return None
    playbook = get_playbook(result.failure_mode)
    if playbook is None:
        return None
    return playbook, result.failure_mode


def _try_inline_recovery(
    func: Callable,
    args: Any,
    kwargs: Any,
    span_ctx: AgentContext,
    error: BaseException,
    record_output: bool,
    name: str,
    classifier: Classifier,
    store: TraceStore,
    attributor: CausalAttributor | None = None,
    max_retries: int = 1,
) -> Any:
    """Sync inline recovery: classify → attribute → run playbook → retry."""
    prepared = _prepare_inline_recovery(error, classifier)
    if prepared is None:
        return None
    playbook, failure_mode = prepared

    for attempt_number in range(1, max_retries + 1):
        action: RecoveryAction = asyncio.run(
            _run_playbook(
                playbook=playbook,
                span_ctx=span_ctx,
                error=error,
                failure_mode=failure_mode,
                store=store,
                attributor=attributor,
                attempt_number=attempt_number,
            )
        )
        if not action.should_retry:
            return None
        try:
            return func(*args, **kwargs)
        except BaseException:
            if attempt_number == max_retries:
                return None
    return None


async def _try_inline_recovery_async(
    func: Callable,
    args: Any,
    kwargs: Any,
    span_ctx: AgentContext,
    error: BaseException,
    record_output: bool,
    name: str,
    classifier: Classifier,
    store: TraceStore,
    attributor: CausalAttributor | None = None,
    max_retries: int = 1,
) -> Any:
    """Async inline recovery: classify → attribute → run playbook → retry."""
    prepared = _prepare_inline_recovery(error, classifier)
    if prepared is None:
        return None
    playbook, failure_mode = prepared

    for attempt_number in range(1, max_retries + 1):
        action: RecoveryAction = await _run_playbook(
            playbook=playbook,
            span_ctx=span_ctx,
            error=error,
            failure_mode=failure_mode,
            store=store,
            attributor=attributor,
            attempt_number=attempt_number,
        )
        if not action.should_retry:
            return None
        try:
            return await func(*args, **kwargs)
        except BaseException:
            if attempt_number == max_retries:
                return None
    return None


def tool_call(*, return_snapshot: bool = False, span_name: str | None = None) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = get_context()
            if ctx is None:
                return func(*args, **kwargs)

            name = span_name or f"tool.{func.__name__}"
            otel_attrs = _get_otel_attributes(ctx, "tool_call")
            otel_attrs["agenticu.tool_name"] = func.__name__
            otel_attrs["agenticu.input"] = str(_capture_input(func, args, kwargs))

            with TRACER.start_as_current_span(
                name, kind=SpanKind.CLIENT, attributes=otel_attrs
            ) as otel_span:
                try:
                    result = func(*args, **kwargs)
                    if return_snapshot:
                        otel_span.set_attribute("agenticu.output", str(result)[:2000])
                    otel_span.set_attribute("agenticu.tool_success", True)
                    return result
                except BaseException as e:
                    otel_span.set_attribute("agenticu.error", str(e))
                    otel_span.set_attribute("agenticu.tool_success", False)
                    otel_span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = get_context()
            if ctx is None:
                return await func(*args, **kwargs)

            name = span_name or f"tool.{func.__name__}"
            otel_attrs = _get_otel_attributes(ctx, "tool_call")
            otel_attrs["agenticu.tool_name"] = func.__name__
            otel_attrs["agenticu.input"] = str(_capture_input(func, args, kwargs))

            with TRACER.start_as_current_span(
                name, kind=SpanKind.CLIENT, attributes=otel_attrs
            ) as otel_span:
                try:
                    result = await func(*args, **kwargs)
                    if return_snapshot:
                        otel_span.set_attribute("agenticu.output", str(result)[:2000])
                    otel_span.set_attribute("agenticu.tool_success", True)
                    return result
                except BaseException as e:
                    otel_span.set_attribute("agenticu.error", str(e))
                    otel_span.set_attribute("agenticu.tool_success", False)
                    otel_span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


def handoff(
    *,
    target_agent: str = "",
    span_name: str | None = None,
    state_snapshot: bool = True,
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = get_context()
            if ctx is None:
                return func(*args, **kwargs)

            name = span_name or f"handoff.to_{target_agent or '?'}"
            otel_attrs = _get_otel_attributes(ctx, "handoff")
            otel_attrs["agenticu.target_agent"] = target_agent
            otel_attrs["agenticu.source_agent"] = ctx.agent_id

            with TRACER.start_as_current_span(
                name, kind=SpanKind.INTERNAL, attributes=otel_attrs
            ) as otel_span:
                try:
                    result = func(*args, **kwargs)
                    if state_snapshot:
                        otel_span.set_attribute("agenticu.handoff_state", str(result)[:2000])
                    return result
                except BaseException as e:
                    otel_span.set_attribute("agenticu.error", str(e))
                    otel_span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = get_context()
            if ctx is None:
                return await func(*args, **kwargs)

            name = span_name or f"handoff.to_{target_agent or '?'}"
            otel_attrs = _get_otel_attributes(ctx, "handoff")
            otel_attrs["agenticu.target_agent"] = target_agent
            otel_attrs["agenticu.source_agent"] = ctx.agent_id

            with TRACER.start_as_current_span(
                name, kind=SpanKind.INTERNAL, attributes=otel_attrs
            ) as otel_span:
                try:
                    result = await func(*args, **kwargs)
                    if state_snapshot:
                        otel_span.set_attribute("agenticu.handoff_state", str(result)[:2000])
                    return result
                except BaseException as e:
                    otel_span.set_attribute("agenticu.error", str(e))
                    otel_span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


def decision(*, span_name: str | None = None, record_rationale: bool = True) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = get_context()
            if ctx is None:
                return func(*args, **kwargs)

            name = span_name or f"decision.{func.__name__}"
            otel_attrs = _get_otel_attributes(ctx, "decision")

            with TRACER.start_as_current_span(
                name, kind=SpanKind.INTERNAL, attributes=otel_attrs
            ) as otel_span:
                try:
                    result = func(*args, **kwargs)
                    if record_rationale:
                        otel_span.set_attribute("agenticu.decision_result", str(result)[:1000])
                    return result
                except BaseException as e:
                    otel_span.set_attribute("agenticu.error", str(e))
                    otel_span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = get_context()
            if ctx is None:
                return await func(*args, **kwargs)

            name = span_name or f"decision.{func.__name__}"
            otel_attrs = _get_otel_attributes(ctx, "decision")

            with TRACER.start_as_current_span(
                name, kind=SpanKind.INTERNAL, attributes=otel_attrs
            ) as otel_span:
                try:
                    result = await func(*args, **kwargs)
                    if record_rationale:
                        otel_span.set_attribute("agenticu.decision_result", str(result)[:1000])
                    return result
                except BaseException as e:
                    otel_span.set_attribute("agenticu.error", str(e))
                    otel_span.set_status(Status(StatusCode.ERROR, str(e)))
                    raise

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator
