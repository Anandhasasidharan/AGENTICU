from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from agenticu.models import AgentContext

_current_context: ContextVar[AgentContext | None] = ContextVar("_agenticu_context", default=None)


def get_context() -> AgentContext | None:
    return _current_context.get()


def set_context(ctx: AgentContext | None) -> None:
    if ctx is None:
        _current_context.set(None)
    else:
        _current_context.set(ctx)


def get_current_trace_id() -> str | None:
    ctx = get_context()
    return ctx.trace_id if ctx else None


def get_current_span_id() -> str | None:
    ctx = get_context()
    return ctx.span_id if ctx else None


def get_current_agent_id() -> str | None:
    ctx = get_context()
    return ctx.agent_id if ctx else None


class ContextScope:
    """Context manager to temporarily set agent context.

    Used internally by decorators to ensure proper context isolation
    across concurrent agent executions.
    """

    def __init__(self, ctx: AgentContext):
        self._ctx = ctx
        self._token: Any = None

    def __enter__(self) -> AgentContext:
        self._token = _current_context.set(self._ctx)
        return self._ctx

    def __exit__(self, *args: Any) -> None:
        if self._token is not None:
            _current_context.reset(self._token)
