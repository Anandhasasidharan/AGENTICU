from __future__ import annotations

import pytest

from agenticu.collector.processor import TraceProcessor
from agenticu.models import Span, SpanStatus


def test_process_valid_span():
    proc = TraceProcessor()
    span = Span(span_id="s1", trace_id="t1", status=SpanStatus.OK)
    result = proc.process(span)
    assert result.span_id == "s1"


def test_duplicate_span_id_raises():
    proc = TraceProcessor()
    Span(span_id="s1", trace_id="t1", status=SpanStatus.OK)
    proc.process(Span(span_id="s1", trace_id="t1", status=SpanStatus.OK))
    with pytest.raises(ValueError, match="Duplicate span_id"):
        proc.process(Span(span_id="s1", trace_id="t2", status=SpanStatus.OK))


def test_error_span_without_message_gets_default():
    proc = TraceProcessor()
    span = Span(span_id="s2", trace_id="t1", status=SpanStatus.ERROR)
    result = proc.process(span)
    assert result.error_message == "No error message captured"


def test_clear_resets_dedup():
    proc = TraceProcessor()
    proc.process(Span(span_id="s1", trace_id="t1", status=SpanStatus.OK))
    proc.clear()
    proc.process(Span(span_id="s1", trace_id="t2", status=SpanStatus.OK))
