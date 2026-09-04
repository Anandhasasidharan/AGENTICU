from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from agenticu.models import FailureMode
from agenticu.tui.client import AgentICUClient, TUIError


def _short(value: object, width: int = 42) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= width else text[: width - 1] + "…"


class AgentICUApp(App):
    """Full ops console for AgentICU.

    Tabs: Dashboard | Traces | Failures | Forecast | Attribution | Recover.
    All data comes from the AgentICU REST API (see ``AgentICUClient``).
    """

    TITLE = "AgentICU Ops Console"
    CSS = """
    TabbedContent { height: 1fr; }
    DataTable { height: 1fr; }
    #detail, #result { height: 1fr; border: solid green; padding: 1; }
    Input { width: 1fr; }
    Button { margin: 0 1; }
    """

    def __init__(self, base_url: str, api_key: str = ""):
        super().__init__()
        self.client = AgentICUClient(base_url=base_url, api_key=api_key)
        self.server_url = base_url

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="dashboard"):
            with TabPane("Dashboard", id="dashboard"):
                yield Static(f"Server: {self.server_url}", id="dash-server")
                yield Static("Loading…", id="dash-health")
                yield Static("", id="dash-metrics")
                yield Static("", id="dash-tracker")
                yield Button("Refresh", id="dash-refresh", variant="primary")
            with TabPane("Traces", id="traces"):
                with Horizontal():
                    yield Input(placeholder="agent_id filter (optional)", id="traces-agent")
                    yield Input(placeholder="status filter (optional)", id="traces-status")
                    yield Button("Load", id="traces-load", variant="primary")
                yield DataTable(id="traces-table")
                with Horizontal():
                    yield Input(placeholder="trace_id for detail…", id="trace-detail-id")
                    yield Button("Show detail", id="trace-detail-btn")
                yield RichLog(id="traces-detail", highlight=True, markup=True)
            with TabPane("Failures", id="failures"):
                with Horizontal():
                    yield Input(placeholder="mode filter, e.g. 2.3 (optional)", id="failures-mode")
                    yield Input(placeholder="agent_id filter (optional)", id="failures-agent")
                    yield Button("Load", id="failures-load", variant="primary")
                yield DataTable(id="failures-table")
            with TabPane("Forecast", id="forecast"):
                with Horizontal():
                    yield Input(placeholder="source_agent", id="fc-source")
                    yield Input(placeholder="target_agent", id="fc-target")
                    yield Button("Predict", id="fc-go", variant="primary")
                yield RichLog(id="fc-result", highlight=True, markup=True)
            with TabPane("Attribution", id="attribution"):
                with Horizontal():
                    yield Input(placeholder="trace_id", id="attr-trace")
                    yield Input(placeholder="failure span_id", id="attr-span")
                    yield Button("Attribute", id="attr-go", variant="primary")
                yield RichLog(id="attr-result", highlight=True, markup=True)
            with TabPane("Recover", id="recover"):
                with Vertical():
                    yield Input(placeholder="trace_id", id="rec-trace")
                    yield Input(
                        placeholder="mode, e.g. 2.3 (valid: "
                        + ", ".join(m.value for m in FailureMode)
                        + ")",
                        id="rec-mode",
                    )
                    yield Button("Trigger recovery", id="rec-go", variant="warning")
                yield RichLog(id="rec-result", highlight=True, markup=True)
        yield Footer()

    async def on_mount(self) -> None:
        self._setup_tables()
        await self.refresh_dashboard()
        self.set_interval(15, self.refresh_dashboard)

    def _setup_tables(self) -> None:
        traces = self.query_one("#traces-table", DataTable)
        traces.add_columns("span_id", "trace_id", "agent", "type", "status", "mode", "error")
        failures = self.query_one("#failures-table", DataTable)
        failures.add_columns("trace_id", "span_id", "agent", "mode", "error", "timestamp")

    # ------------------------------------------------------------------ #
    # Dashboard
    # ------------------------------------------------------------------ #

    async def refresh_dashboard(self) -> None:
        try:
            health = await self.client.health()
        except TUIError as e:
            self.query_one("#dash-health", Static).update(f"[red]Server unreachable: {e}[/red]")
            return
        self.query_one("#dash-health", Static).update(
            f"[green]● {health.get('status', 'ok')}[/green]  ({self.server_url})"
        )
        try:
            m = await self.client.recovery_metrics()
            rate = m.get("success_rate", 0.0)
            self.query_one("#dash-metrics", Static).update(
                f"Recovery — total: {m.get('total', 0)}  "
                f"succeeded: {m.get('succeeded', 0)}  failed: {m.get('failed', 0)}  "
                f"rate: {rate:.0%}"
            )
        except TUIError as e:
            self.query_one("#dash-metrics", Static).update(f"[yellow]metrics: {e}[/yellow]")
        try:
            t = await self.client.outcome_tracker_status()
            self.query_one("#dash-tracker", Static).update(
                f"OutcomeTracker — running: {t.get('is_running')}  "
                f"learn calls: {t.get('total_learn_calls', 0)}  "
                f"last: {t.get('last_learned_at') or 'never'}"
            )
        except TUIError as e:
            self.query_one("#dash-tracker", Static).update(f"[yellow]tracker: {e}[/yellow]")

    @on(Button.Pressed, "#dash-refresh")
    async def _on_dash_refresh(self) -> None:
        await self.refresh_dashboard()
        self.notify("Dashboard refreshed")

    # ------------------------------------------------------------------ #
    # Traces
    # ------------------------------------------------------------------ #

    @on(Button.Pressed, "#traces-load")
    async def _on_traces_load(self) -> None:
        agent = self.query_one("#traces-agent", Input).value.strip() or None
        status = self.query_one("#traces-status", Input).value.strip() or None
        table = self.query_one("#traces-table", DataTable)
        table.clear()
        try:
            spans = await self.client.list_traces(agent_id=agent, status=status)
        except TUIError as e:
            self.notify(f"Failed to load traces: {e}", severity="error")
            return
        for s in spans:
            table.add_row(
                _short(s.get("span_id"), 12),
                _short(s.get("trace_id"), 12),
                _short(s.get("agent_id"), 16),
                _short(s.get("span_type"), 10),
                _short(s.get("status"), 8),
                _short(s.get("failure_mode"), 6),
                _short(s.get("error")),
            )
        self.notify(f"Loaded {len(spans)} spans")

    @on(Button.Pressed, "#trace-detail-btn")
    async def _on_trace_detail(self) -> None:
        trace_id = self.query_one("#trace-detail-id", Input).value.strip()
        log = self.query_one("#traces-detail", RichLog)
        if not trace_id:
            self.notify("Enter a trace_id first", severity="warning")
            return
        try:
            spans = await self.client.get_trace(trace_id)
            try:
                forecasts = await self.client.forecast_trace(trace_id)
            except TUIError:
                forecasts = []
        except TUIError as e:
            log.write(f"[red]Error: {e}[/red]")
            return
        log.clear()
        log.write(f"[bold]Trace {trace_id}[/bold] — {len(spans)} spans")
        for s in spans:
            log.write(
                f"  {s.get('span_type')} [{s.get('agent_id')}] "
                f"status={s.get('status')} mode={s.get('failure_mode')} "
                f"err={_short(s.get('error'), 60)}"
            )
        if forecasts:
            log.write("[bold]Forecasts at handoffs:[/bold]")
            for f in forecasts:
                flag = "⚠ EXCEEDED" if f.get("threshold_exceeded") else "ok"
                log.write(
                    f"  {f.get('source_agent')} → {f.get('target_agent')}: "
                    f"P={f.get('failure_probability', 0):.0%} [{flag}]"
                )

    # ------------------------------------------------------------------ #
    # Failures
    # ------------------------------------------------------------------ #

    @on(Button.Pressed, "#failures-load")
    async def _on_failures_load(self) -> None:
        mode = self.query_one("#failures-mode", Input).value.strip() or None
        agent = self.query_one("#failures-agent", Input).value.strip() or None
        table = self.query_one("#failures-table", DataTable)
        table.clear()
        try:
            failures = await self.client.list_failures(failure_mode=mode, agent_id=agent)
        except TUIError as e:
            self.notify(f"Failed to load failures: {e}", severity="error")
            return
        for f in failures:
            table.add_row(
                _short(f.get("trace_id"), 12),
                _short(f.get("span_id"), 12),
                _short(f.get("agent_id"), 16),
                _short(f.get("failure_mode"), 6),
                _short(f.get("error")),
                _short(f.get("timestamp"), 20),
            )
        self.notify(f"Loaded {len(failures)} failures")

    # ------------------------------------------------------------------ #
    # Forecast
    # ------------------------------------------------------------------ #

    @on(Button.Pressed, "#fc-go")
    async def _on_forecast(self) -> None:
        src = self.query_one("#fc-source", Input).value.strip()
        tgt = self.query_one("#fc-target", Input).value.strip()
        log = self.query_one("#fc-result", RichLog)
        if not src or not tgt:
            self.notify("Enter both source and target agents", severity="warning")
            return
        try:
            r = await self.client.forecast(src, tgt)
        except TUIError as e:
            log.write(f"[red]Error: {e}[/red]")
            return
        flag = (
            "[red]⚠ THRESHOLD EXCEEDED[/red]"
            if r.get("threshold_exceeded")
            else "[green]below threshold[/green]"
        )
        log.write(
            f"[bold]{r.get('source_agent')} → {r.get('target_agent')}[/bold]\n"
            f"  P(failure) = {r.get('failure_probability', 0):.1%}  {flag}\n"
            f"  predicted mode: {r.get('predicted_mode')}  "
            f"confidence: {r.get('confidence', 0):.0%}  samples: {r.get('samples_seen', 0)}"
        )

    # ------------------------------------------------------------------ #
    # Attribution
    # ------------------------------------------------------------------ #

    @on(Button.Pressed, "#attr-go")
    async def _on_attribute(self) -> None:
        trace_id = self.query_one("#attr-trace", Input).value.strip()
        span_id = self.query_one("#attr-span", Input).value.strip()
        log = self.query_one("#attr-result", RichLog)
        if not trace_id or not span_id:
            self.notify("Enter both trace_id and span_id", severity="warning")
            return
        try:
            r = await self.client.attribute(trace_id, span_id)
        except TUIError as e:
            log.write(f"[red]Error: {e}[/red]")
            return
        chain = " → ".join(r.get("attribution_chain", []))
        log.write(
            f"[bold]Root cause: {r.get('root_agent_id')}[/bold] "
            f"(confidence {r.get('confidence', 0):.0%})\n"
            f"  chain: {chain}\n"
            f"  {r.get('root_cause_description')}"
        )

    # ------------------------------------------------------------------ #
    # Recover
    # ------------------------------------------------------------------ #

    @on(Button.Pressed, "#rec-go")
    async def _on_recover(self) -> None:
        trace_id = self.query_one("#rec-trace", Input).value.strip()
        mode = self.query_one("#rec-mode", Input).value.strip()
        log = self.query_one("#rec-result", RichLog)
        if not trace_id or not mode:
            self.notify("Enter both trace_id and failure_mode", severity="warning")
            return
        try:
            FailureMode(mode)
        except ValueError:
            valid = ", ".join(m.value for m in FailureMode)
            log.write(f"[red]Invalid mode '{mode}'. Valid: {valid}[/red]")
            return
        try:
            r = await self.client.trigger_recovery(trace_id, mode)
        except TUIError as e:
            log.write(f"[red]Error: {e}[/red]")
            return
        status = "[green]SUCCESS[/green]" if r.get("success") else "[red]FAILED[/red]"
        log.write(
            f"Recovery {status}\n"
            f"  attempt: {r.get('attempt_id')}  strategy: {r.get('strategy')}\n"
            f"  error: {r.get('error') or '—'}"
        )

    async def on_unmount(self) -> None:
        await self.client.close()
