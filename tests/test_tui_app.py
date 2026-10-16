"""Headless tests for the Textual ops console (``agenticu.tui.app``).

Most tests drive the app against an in-memory ``FakeClient`` so every tab,
button handler and error branch is exercised without a network. One test
wires the real :class:`AgentICUClient` through ``respx`` to prove the app
talks to the HTTP layer correctly.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from textual.widgets import Button, DataTable, Input, RichLog, Static, TabbedContent

from agenticu.tui.app import AgentICUApp, _short
from agenticu.tui.client import TUIError

BASE = "http://localhost:8000"
TABS = ["dashboard", "traces", "failures", "forecast", "attribution", "recover"]


class FakeClient:
    """In-memory stand-in for ``AgentICUClient``.

    Records every method it is asked to call and can be configured to raise
    ``TUIError`` for a given method via keyword arguments.
    """

    def __init__(self, **errors: Exception) -> None:
        self.errors = errors
        self.calls: list[str] = []
        self.closed = False

        self.health_data: dict[str, Any] = {"status": "ok"}
        self.metrics_data: dict[str, Any] = {
            "total": 4,
            "succeeded": 3,
            "failed": 1,
            "success_rate": 0.75,
        }
        self.tracker_data: dict[str, Any] = {
            "is_running": True,
            "total_learn_calls": 7,
            "last_learned_at": "2026-01-01T00:00:00Z",
        }
        self.spans: list[dict[str, Any]] = [
            {
                "span_id": "s1",
                "trace_id": "t1",
                "agent_id": "agent-a",
                "span_type": "agent",
                "status": "ok",
                "failure_mode": None,
                "error": None,
            },
            {
                "span_id": "s2",
                "trace_id": "t1",
                "agent_id": "agent-b",
                "span_type": "tool",
                "status": "failure",
                "failure_mode": "2.3",
                "error": "boom",
            },
        ]
        self.failures: list[dict[str, Any]] = [
            {
                "trace_id": "t1",
                "span_id": "s2",
                "agent_id": "agent-b",
                "failure_mode": "2.3",
                "error": "boom",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ]
        self.trace_forecasts: list[dict[str, Any]] = [
            {
                "source_agent": "agent-a",
                "target_agent": "agent-b",
                "failure_probability": 0.9,
                "threshold_exceeded": True,
            }
        ]
        self.forecast_data: dict[str, Any] = {
            "source_agent": "agent-a",
            "target_agent": "agent-b",
            "failure_probability": 0.82,
            "predicted_mode": "2.3",
            "confidence": 0.9,
            "samples_seen": 12,
            "threshold_exceeded": True,
        }
        self.attribution_data: dict[str, Any] = {
            "root_agent_id": "agent-a",
            "confidence": 0.8,
            "attribution_chain": ["agent-a", "agent-b"],
            "root_cause_description": "bad tool output",
        }
        self.recovery_data: dict[str, Any] = {
            "attempt_id": "att-1",
            "success": True,
            "strategy": "retry",
            "error": None,
        }

    def _record(self, name: str) -> None:
        self.calls.append(name)
        if name in self.errors:
            raise self.errors[name]

    async def health(self) -> dict[str, Any]:
        self._record("health")
        return self.health_data

    async def recovery_metrics(self) -> dict[str, Any]:
        self._record("recovery_metrics")
        return self.metrics_data

    async def outcome_tracker_status(self) -> dict[str, Any]:
        self._record("outcome_tracker_status")
        return self.tracker_data

    async def list_traces(
        self,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._record("list_traces")
        return self.spans

    async def get_trace(self, trace_id: str) -> list[dict[str, Any]]:
        self._record("get_trace")
        return self.spans

    async def forecast_trace(self, trace_id: str) -> list[dict[str, Any]]:
        self._record("forecast_trace")
        return self.trace_forecasts

    async def list_failures(
        self,
        failure_mode: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._record("list_failures")
        return self.failures

    async def forecast(self, source_agent: str, target_agent: str) -> dict[str, Any]:
        self._record("forecast")
        return self.forecast_data

    async def attribute(self, trace_id: str, span_id: str) -> dict[str, Any]:
        self._record("attribute")
        return self.attribution_data

    async def trigger_recovery(self, trace_id: str, failure_mode: str) -> dict[str, Any]:
        self._record("trigger_recovery")
        return self.recovery_data

    async def close(self) -> None:
        self.closed = True


def _make_app(fake: FakeClient) -> AgentICUApp:
    app = AgentICUApp(base_url=BASE)
    app.client = fake  # type: ignore[assignment]
    return app


async def _settle(pilot: Any, cycles: int = 6) -> None:
    for _ in range(cycles):
        await pilot.pause()


async def _goto(app: AgentICUApp, pilot: Any, tab_id: str) -> None:
    """Activate a tab and let its lazily-mounted pane finish composing."""
    app.query_one(TabbedContent).active = tab_id
    await _settle(pilot)


def _press(app: AgentICUApp, selector: str) -> None:
    app.query_one(selector, Button).press()


def _static_text(app: AgentICUApp, selector: str) -> str:
    return str(app.query_one(selector, Static).render())


def _log_text(app: AgentICUApp, selector: str) -> str:
    log = app.query_one(selector, RichLog)
    lines = []
    for strip in log.lines:
        text = getattr(strip, "text", None)
        if text is None:
            text = "".join(segment.text for segment in strip)
        lines.append(text)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def test_short_truncates_and_handles_none():
    assert _short(None) == ""
    assert _short("abc") == "abc"

    truncated = _short("x" * 50, width=10)
    assert len(truncated) == 10
    assert truncated.endswith("…")
    assert not truncated.endswith("xx…x")


# --------------------------------------------------------------------------- #
# Mounting + dashboard
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_app_mounts_all_tabs_and_shows_dashboard():
    fake = FakeClient()
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)

        assert [pane.id for pane in app.query("TabPane")] == TABS
        assert "ok" in _static_text(app, "#dash-health")
        assert "rate: 75%" in _static_text(app, "#dash-metrics")
        assert "running: True" in _static_text(app, "#dash-tracker")

    assert fake.closed, "on_unmount must close the client"


@pytest.mark.asyncio
async def test_dashboard_reports_unreachable_server():
    fake = FakeClient(health=TUIError("boom"))
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)

        assert "Server unreachable" in _static_text(app, "#dash-health")
        # health failed, so the optional panels are never queried
        assert "recovery_metrics" not in fake.calls
        assert "outcome_tracker_status" not in fake.calls


@pytest.mark.asyncio
async def test_dashboard_surfaces_optional_component_errors():
    fake = FakeClient(
        recovery_metrics=TUIError("component not wired"),
        outcome_tracker_status=TUIError("component not wired"),
    )
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)

        assert "metrics:" in _static_text(app, "#dash-metrics")
        assert "tracker:" in _static_text(app, "#dash-tracker")


@pytest.mark.asyncio
async def test_dashboard_refresh_button_reloads():
    fake = FakeClient()
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        before = fake.calls.count("health")

        _press(app, "#dash-refresh")
        await _settle(pilot)

        assert fake.calls.count("health") > before


# --------------------------------------------------------------------------- #
# Traces
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_traces_load_populates_table():
    fake = FakeClient()
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "traces")

        app.query_one("#traces-agent", Input).value = "agent-a"
        _press(app, "#traces-load")
        await _settle(pilot)

        assert app.query_one("#traces-table", DataTable).row_count == 2
        assert "list_traces" in fake.calls


@pytest.mark.asyncio
async def test_traces_load_error_leaves_table_empty():
    fake = FakeClient(list_traces=TUIError("down"))
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "traces")

        _press(app, "#traces-load")
        await _settle(pilot)

        assert app.query_one("#traces-table", DataTable).row_count == 0


@pytest.mark.asyncio
async def test_trace_detail_requires_a_trace_id():
    fake = FakeClient()
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "traces")

        _press(app, "#trace-detail-btn")
        await _settle(pilot)

        assert "get_trace" not in fake.calls
        assert _log_text(app, "#traces-detail") == ""


@pytest.mark.asyncio
async def test_trace_detail_renders_spans_and_handoff_forecasts():
    fake = FakeClient()
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "traces")

        app.query_one("#trace-detail-id", Input).value = "t1"
        _press(app, "#trace-detail-btn")
        await _settle(pilot)

        text = _log_text(app, "#traces-detail")
        assert "Trace t1" in text
        assert "Forecasts at handoffs" in text
        assert "EXCEEDED" in text


@pytest.mark.asyncio
async def test_trace_detail_error_is_written_to_log():
    fake = FakeClient(get_trace=TUIError("down"))
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "traces")

        app.query_one("#trace-detail-id", Input).value = "t1"
        _press(app, "#trace-detail-btn")
        await _settle(pilot)

        assert "Error:" in _log_text(app, "#traces-detail")


# --------------------------------------------------------------------------- #
# Failures
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_failures_load_populates_table():
    fake = FakeClient()
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "failures")

        app.query_one("#failures-mode", Input).value = "2.3"
        _press(app, "#failures-load")
        await _settle(pilot)

        assert app.query_one("#failures-table", DataTable).row_count == 1
        assert "list_failures" in fake.calls


@pytest.mark.asyncio
async def test_failures_load_error_leaves_table_empty():
    fake = FakeClient(list_failures=TUIError("down"))
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "failures")

        _press(app, "#failures-load")
        await _settle(pilot)

        assert app.query_one("#failures-table", DataTable).row_count == 0


# --------------------------------------------------------------------------- #
# Forecast
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_forecast_requires_both_agents():
    fake = FakeClient()
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "forecast")

        _press(app, "#fc-go")
        await _settle(pilot)

        assert "forecast" not in fake.calls
        assert _log_text(app, "#fc-result") == ""


@pytest.mark.asyncio
async def test_forecast_renders_result_and_flags_threshold():
    fake = FakeClient()
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "forecast")

        app.query_one("#fc-source", Input).value = "agent-a"
        app.query_one("#fc-target", Input).value = "agent-b"
        _press(app, "#fc-go")
        await _settle(pilot)

        text = _log_text(app, "#fc-result")
        assert "agent-a" in text and "agent-b" in text
        assert "82.0%" in text
        assert "THRESHOLD EXCEEDED" in text


@pytest.mark.asyncio
async def test_forecast_error_is_written_to_log():
    fake = FakeClient(forecast=TUIError("not wired"))
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "forecast")

        app.query_one("#fc-source", Input).value = "a"
        app.query_one("#fc-target", Input).value = "b"
        _press(app, "#fc-go")
        await _settle(pilot)

        assert "Error:" in _log_text(app, "#fc-result")


# --------------------------------------------------------------------------- #
# Attribution
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_attribution_requires_both_ids():
    fake = FakeClient()
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "attribution")

        _press(app, "#attr-go")
        await _settle(pilot)

        assert "attribute" not in fake.calls


@pytest.mark.asyncio
async def test_attribution_renders_root_cause_chain():
    fake = FakeClient()
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "attribution")

        app.query_one("#attr-trace", Input).value = "t1"
        app.query_one("#attr-span", Input).value = "s1"
        _press(app, "#attr-go")
        await _settle(pilot)

        text = _log_text(app, "#attr-result")
        assert "agent-a" in text
        assert "agent-a → agent-b" in text
        assert "bad tool output" in text


# --------------------------------------------------------------------------- #
# Recover
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_recover_requires_inputs():
    fake = FakeClient()
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "recover")

        _press(app, "#rec-go")
        await _settle(pilot)

        assert "trigger_recovery" not in fake.calls


@pytest.mark.asyncio
async def test_recover_rejects_invalid_mode_without_calling_server():
    fake = FakeClient()
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "recover")

        app.query_one("#rec-trace", Input).value = "t1"
        app.query_one("#rec-mode", Input).value = "9.9"
        _press(app, "#rec-go")
        await _settle(pilot)

        assert "trigger_recovery" not in fake.calls
        assert "Invalid mode" in _log_text(app, "#rec-result")


@pytest.mark.asyncio
async def test_recover_success_renders_result():
    fake = FakeClient()
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "recover")

        app.query_one("#rec-trace", Input).value = "t1"
        app.query_one("#rec-mode", Input).value = "2.3"
        _press(app, "#rec-go")
        await _settle(pilot)

        text = _log_text(app, "#rec-result")
        assert "SUCCESS" in text
        assert "att-1" in text


@pytest.mark.asyncio
async def test_recover_server_error_is_written_to_log():
    fake = FakeClient(trigger_recovery=TUIError("down"))
    app = _make_app(fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _settle(pilot)
        await _goto(app, pilot, "recover")

        app.query_one("#rec-trace", Input).value = "t1"
        app.query_one("#rec-mode", Input).value = "2.3"
        _press(app, "#rec-go")
        await _settle(pilot)

        assert "Error:" in _log_text(app, "#rec-result")


# --------------------------------------------------------------------------- #
# Integration: app + real client + mocked HTTP
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_app_works_against_real_client_over_mocked_http():
    app = AgentICUApp(base_url=BASE)
    with respx.mock(base_url=BASE) as mock:
        mock.get("/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
        mock.get("/api/v1/metrics/recovery").mock(
            return_value=httpx.Response(200, json={"total": 2, "succeeded": 2, "success_rate": 1.0})
        )
        mock.get("/api/v1/outcome-tracker").mock(
            return_value=httpx.Response(200, json={"is_running": False})
        )
        mock.get("/api/v1/traces").mock(
            return_value=httpx.Response(200, json={"spans": [{"span_id": "s1", "trace_id": "t1"}]})
        )

        async with app.run_test(size=(120, 40)) as pilot:
            await _settle(pilot)
            assert "ok" in _static_text(app, "#dash-health")

            await _goto(app, pilot, "traces")
            _press(app, "#traces-load")
            await _settle(pilot)

            assert app.query_one("#traces-table", DataTable).row_count == 1
