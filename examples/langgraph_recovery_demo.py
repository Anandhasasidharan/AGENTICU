"""Exercise SDK recovery, persistence, API queries, and the real terminal UI."""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from opentelemetry.trace import get_tracer_provider
from textual.widgets import Button, DataTable, Input, TabbedContent

from agenticu import decision, get_current_trace_id, tool_call, trace
from agenticu.models import FailureMode, RecoveryAction
from agenticu.tui.app import AgentICUApp

AGENT = "langgraph-agent"
MODE = FailureMode.STEP_REPETITION.value
STEPS = ("collect", "verify")


class WorkflowState(TypedDict):
    completed: list[str]
    next_step: str | None


def run_workflow() -> str:
    checkpoint: list[str] = []
    skip_completed = False
    directives: list[RecoveryAction] = []

    @decision()
    def plan(state: WorkflowState) -> dict:
        step = next(
            (step for step in STEPS if not skip_completed or step not in state["completed"]),
            None,
        )
        return {"next_step": step}

    @tool_call(return_snapshot=True)
    def perform(step: str) -> str:
        return f"{step} complete"

    def execute(state: WorkflowState) -> dict:
        step = state["next_step"]
        assert step is not None
        if step in state["completed"]:
            raise RuntimeError(f"Agent kept repeating the same step: {step}")
        perform(step)
        checkpoint.append(step)
        return {"completed": checkpoint.copy()}

    graph = StateGraph(WorkflowState)
    graph.add_node("plan", plan)
    graph.add_node("execute", execute)
    graph.add_edge(START, "plan")
    graph.add_conditional_edges(
        "plan", lambda state: "execute" if state["next_step"] else END, ["execute", END]
    )
    graph.add_edge("execute", "plan")
    workflow = graph.compile()

    def apply_recovery(action: RecoveryAction) -> bool:
        nonlocal skip_completed
        directives.append(action)
        skip_completed = action.should_retry
        return skip_completed

    @trace(agent_id=AGENT, on_failure=apply_recovery)
    def run() -> str:
        final = workflow.invoke({"completed": checkpoint.copy(), "next_step": None})
        assert final["completed"] == list(STEPS)
        trace_id = get_current_trace_id()
        assert trace_id
        return trace_id

    trace_id = run()
    assert len(directives) == 1 and directives[0].target_agent_id == AGENT
    return trace_id


async def verify(server: str, api_key: str, trace_id: str) -> None:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with (
        httpx.AsyncClient(base_url=server, headers=headers, timeout=5) as client,
        asyncio.timeout(15),
    ):
        while True:
            response = await client.get("/api/v1/recovery-attempts", params={"trace_id": trace_id})
            attempts = response.raise_for_status().json()["attempts"]
            if attempts:
                break
            await asyncio.sleep(0.1)

        assert len(attempts) == 1
        attempt = attempts[0]
        assert attempt["outcome"] == "recovered" and attempt["success"] is True
        assert attempt["strategy"] == "recover_step_repetition" and attempt["failure_mode"] == MODE

        response = await client.get(
            "/api/v1/failures", params={"agent_id": AGENT, "failure_mode": MODE}
        )
        failures = response.raise_for_status().json()["failures"]
        failure = next(item for item in failures if item["trace_id"] == trace_id)
        assert failure["category"] == "specification" and failure["severity"] == "error"
        assert failure["span_id"] == attempt["span_id"]

        response = await client.get(f"/api/v1/traces/{trace_id}")
        spans = response.raise_for_status().json()["spans"]
        assert {"agent", "decision", "tool_call"} <= {span["span_type"] for span in spans}

    app = AgentICUApp(server, api_key)
    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one(TabbedContent).active = "failures"
        await pilot.pause()
        app.query_one("#failures-mode", Input).value = MODE
        app.query_one("#failures-agent", Input).value = AGENT
        app.query_one("#failures-load", Button).press()
        await pilot.pause()
        table = app.query_one("#failures-table", DataTable)
        rows = (table.get_row_at(index) for index in range(table.row_count))
        assert any(row[0] == f"{trace_id[:11]}…" and row[2:4] == [AGENT, MODE] for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server", default=os.getenv("AGENTICU_SERVER_URL", "http://localhost:8000")
    )
    args = parser.parse_args()
    server = args.server.rstrip("/")
    api_key = os.environ.get("AGENTICU__API__KEY", "")
    httpx.get(f"{server}/health", timeout=5).raise_for_status()
    os.environ["AGENTICU_SERVER_URL"] = server
    trace_id = run_workflow()
    assert get_tracer_provider().force_flush(), "Trace export did not finish"
    asyncio.run(verify(server, api_key, trace_id))
    print(f"Trace {trace_id} recovered and verified through the API and terminal UI.")


if __name__ == "__main__":
    main()
