from __future__ import annotations

import pytest

from agenticu.classification.classifier import Classifier
from agenticu.classification.signature_db import SignatureDB
from agenticu.collector.storage import TraceStore
from agenticu.models import FailureMode, Span, SpanStatus
from agenticu.recovery.playbook_runner import PlaybookRunner
from agenticu.recovery.recovery_metrics import MetricsTracker


@pytest.fixture
def store() -> TraceStore:
    return TraceStore()


@pytest.fixture
def signature_db() -> SignatureDB:
    return SignatureDB()


@pytest.fixture
def classifier(signature_db: SignatureDB) -> Classifier:
    return Classifier(signature_db=signature_db, fast_path_only=True)


@pytest.fixture
def metrics() -> MetricsTracker:
    return MetricsTracker()


@pytest.fixture
def runner(store: TraceStore, metrics: MetricsTracker) -> PlaybookRunner:
    return PlaybookRunner(
        store=store,
        metrics=metrics,
        max_retries=2,
        escalate_after=2,
        cooldown_seconds=0,
    )


@pytest.fixture
def sample_span() -> Span:
    return Span(
        span_id="span-1",
        trace_id="trace-1",
        span_type="agent",
        agent_id="test-agent",
        input={"query": "hello"},
        output={"result": "world"},
        attributes={"agenticu.agent_id": "test-agent"},
        status=SpanStatus.FAILURE,
        failure_mode=FailureMode.STEP_REPETITION,
        error_message="repeat detected",
    )
