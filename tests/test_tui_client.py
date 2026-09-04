from __future__ import annotations

import httpx
import pytest
import respx

from agenticu.tui.client import AgentICUClient, TUIError

BASE = "http://localhost:8000"


@pytest.fixture
def client() -> AgentICUClient:
    c = AgentICUClient(base_url=BASE)
    yield c


@pytest.mark.asyncio
async def test_health(client: AgentICUClient):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
        assert await client.health() == {"status": "ok"}
    await client.close()


@pytest.mark.asyncio
async def test_list_traces(client: AgentICUClient):
    spans = [{"span_id": "s1", "trace_id": "t1", "status": "ok"}]
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/api/v1/traces").mock(
            return_value=httpx.Response(200, json={"spans": spans})
        )
        assert await client.list_traces(agent_id="a", status="ok") == spans
        assert route.calls[0].request.url.params["agent_id"] == "a"
    await client.close()


@pytest.mark.asyncio
async def test_get_trace(client: AgentICUClient):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/traces/t1").mock(return_value=httpx.Response(200, json={"spans": []}))
        assert await client.get_trace("t1") == []
    await client.close()


@pytest.mark.asyncio
async def test_list_failures(client: AgentICUClient):
    failures = [{"trace_id": "t1", "failure_mode": "2.3"}]
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/failures").mock(
            return_value=httpx.Response(200, json={"failures": failures})
        )
        assert await client.list_failures() == failures
    await client.close()


@pytest.mark.asyncio
async def test_trigger_recovery(client: AgentICUClient):
    result = {"attempt_id": "x", "success": True, "strategy": "p", "error": None}
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/v1/recover").mock(return_value=httpx.Response(200, json=result))
        assert await client.trigger_recovery("t1", "2.3") == result
    await client.close()


@pytest.mark.asyncio
async def test_recovery_metrics(client: AgentICUClient):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/metrics/recovery").mock(
            return_value=httpx.Response(200, json={"total": 1})
        )
        assert (await client.recovery_metrics())["total"] == 1
    await client.close()


@pytest.mark.asyncio
async def test_forecast_and_attribution(client: AgentICUClient):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/forecast").mock(
            return_value=httpx.Response(200, json={"failure_probability": 0.75})
        )
        mock.get("/api/v1/forecast/trace").mock(
            return_value=httpx.Response(200, json={"forecasts": []})
        )
        mock.get("/api/v1/attribution").mock(
            return_value=httpx.Response(200, json={"root_agent_id": "agent_b"})
        )
        mock.get("/api/v1/outcome-tracker").mock(
            return_value=httpx.Response(200, json={"is_running": True})
        )
        assert (await client.forecast("a", "b"))["failure_probability"] == 0.75
        assert await client.forecast_trace("t1") == []
        assert (await client.attribute("t1", "s1"))["root_agent_id"] == "agent_b"
        assert (await client.outcome_tracker_status())["is_running"] is True
    await client.close()


@pytest.mark.asyncio
async def test_404_becomes_tuierror(client: AgentICUClient):
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v1/forecast").mock(return_value=httpx.Response(404))
        with pytest.raises(TUIError, match="unavailable"):
            await client.forecast("a", "b")
    await client.close()


@pytest.mark.asyncio
async def test_connection_error_becomes_tuierror():
    c = AgentICUClient(base_url="http://127.0.0.1:9")
    with pytest.raises(TUIError, match="Cannot reach"):
        await c.health()
    await c.close()


def test_from_config_defaults():
    c = AgentICUClient.from_config()
    assert c.base_url.startswith("http://")
    assert isinstance(c.api_key, str)
