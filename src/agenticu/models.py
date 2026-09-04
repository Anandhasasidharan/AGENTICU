from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class FailureCategory(StrEnum):
    SPECIFICATION = "specification"
    COORDINATION = "coordination"
    VERIFICATION = "verification"


class FailureMode(StrEnum):
    # Specification (FC1)
    DISOBEY_TASK_SPEC = "1.1"
    DISOBEY_ROLE_SPEC = "1.2"
    STEP_REPETITION = "1.3"
    LOSS_OF_CONVERSATION_HISTORY = "1.4"
    UNAWARE_OF_TERMINATION = "1.5"
    # Coordination (FC2)
    CONVERSATION_RESET = "2.1"
    FAIL_TO_ASK_CLARIFICATION = "2.2"
    TASK_DERAILMENT = "2.3"
    INFORMATION_WITHHOLDING = "2.4"
    IGNORED_OTHER_AGENT_INPUT = "2.5"
    REASONING_ACTION_MISMATCH = "2.6"
    # Verification (FC3)
    PREMATURE_TERMINATION = "3.1"
    NO_INCOMPLETE_VERIFICATION = "3.2"
    INCORRECT_VERIFICATION = "3.3"


FAILURE_CATEGORY_MAP: dict[FailureMode, FailureCategory] = {
    FailureMode.DISOBEY_TASK_SPEC: FailureCategory.SPECIFICATION,
    FailureMode.DISOBEY_ROLE_SPEC: FailureCategory.SPECIFICATION,
    FailureMode.STEP_REPETITION: FailureCategory.SPECIFICATION,
    FailureMode.LOSS_OF_CONVERSATION_HISTORY: FailureCategory.SPECIFICATION,
    FailureMode.UNAWARE_OF_TERMINATION: FailureCategory.SPECIFICATION,
    FailureMode.CONVERSATION_RESET: FailureCategory.COORDINATION,
    FailureMode.FAIL_TO_ASK_CLARIFICATION: FailureCategory.COORDINATION,
    FailureMode.TASK_DERAILMENT: FailureCategory.COORDINATION,
    FailureMode.INFORMATION_WITHHOLDING: FailureCategory.COORDINATION,
    FailureMode.IGNORED_OTHER_AGENT_INPUT: FailureCategory.COORDINATION,
    FailureMode.REASONING_ACTION_MISMATCH: FailureCategory.COORDINATION,
    FailureMode.PREMATURE_TERMINATION: FailureCategory.VERIFICATION,
    FailureMode.NO_INCOMPLETE_VERIFICATION: FailureCategory.VERIFICATION,
    FailureMode.INCORRECT_VERIFICATION: FailureCategory.VERIFICATION,
}


class SpanStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    FAILURE = "failure"


@dataclass
class AgentContext:
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    span_id: str | None = None
    parent_span_id: str | None = None
    agent_id: str = ""
    task_spec: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class SpanEvent:
    name: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    span_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = ""
    parent_span_id: str | None = None
    span_type: str = ""  # agent, tool_call, handoff, decision
    agent_id: str = ""
    input: Any = None
    output: Any = None
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[SpanEvent] = field(default_factory=list)
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    status: SpanStatus = SpanStatus.OK
    failure_mode: FailureMode | None = None
    error_message: str | None = None


@dataclass
class RecoveryAttempt:
    attempt_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = ""
    span_id: str = ""
    failure_mode: FailureMode | None = None
    attempt_number: int = 1
    strategy: str = ""
    success: bool | None = None
    root_agent_id: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error_message: str | None = None


@dataclass
class ClassificationResult:
    failure_mode: FailureMode | None = None
    confidence: float = 0.0
    method: str = ""  # pattern, embedding
    matched_pattern: str | None = None
    trace_snippet: str | None = None


@dataclass
class RecoveryAction:
    should_retry: bool = False
    retry_delay: float = 0.0
    instructions: str = ""
    target_agent_id: str | None = None
    payload: dict = field(default_factory=dict)


@dataclass
class ForecastResult:
    failure_probability: float = 0.0
    predicted_mode: FailureMode | None = None
    confidence: float = 0.0
    source_agent: str = ""
    target_agent: str = ""
    threshold_exceeded: bool = False
    samples_seen: int = 0


@dataclass
class AttributionResult:
    root_agent_id: str | None = None
    confidence: float = 0.0
    attribution_chain: list[str] = field(default_factory=list)
    failure_span_id: str = ""
    root_cause_description: str = ""
