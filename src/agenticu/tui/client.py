from __future__ import annotations

from typing import Any

import httpx


class TUIError(Exception):
    """Raised when the AgentICU server returns an error or is unreachable."""


class AgentICUClient:
    """Async HTTP client for the AgentICU REST API.

    Mirrors every endpoint in ``agenticu.api.routes``. Conditional endpoints
    (forecast / attribution / outcome-tracker) raise :class:`TUIError` with a
    clear message when the server was started without those components wired.
    """

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            resp = await self._client.get(path, params=params)
        except httpx.RequestError as e:
            raise TUIError(f"Cannot reach server at {self.base_url}: {e}") from e
        if resp.status_code == 404:
            raise TUIError(f"Endpoint unavailable (404): {path}")
        if resp.status_code >= 400:
            raise TUIError(f"Server error {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        try:
            resp = await self._client.post(path, json=payload)
        except httpx.RequestError as e:
            raise TUIError(f"Cannot reach server at {self.base_url}: {e}") from e
        if resp.status_code >= 400:
            detail = resp.text[:200]
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            raise TUIError(f"Server error {resp.status_code}: {detail}")
        return resp.json()

    async def health(self) -> dict[str, Any]:
        return await self._get("/health")

    async def list_traces(
        self,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if agent_id:
            params["agent_id"] = agent_id
        if status:
            params["status"] = status
        data = await self._get("/api/v1/traces", params)
        return data.get("spans", [])

    async def get_trace(self, trace_id: str) -> list[dict[str, Any]]:
        data = await self._get(f"/api/v1/traces/{trace_id}")
        return data.get("spans", [])

    async def list_failures(
        self,
        failure_mode: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if failure_mode:
            params["failure_mode"] = failure_mode
        if agent_id:
            params["agent_id"] = agent_id
        data = await self._get("/api/v1/failures", params)
        return data.get("failures", [])

    async def trigger_recovery(self, trace_id: str, failure_mode: str) -> dict[str, Any]:
        return await self._post(
            "/api/v1/recover",
            {"trace_id": trace_id, "failure_mode": failure_mode},
        )

    async def recovery_metrics(self) -> dict[str, Any]:
        return await self._get("/api/v1/metrics/recovery")

    async def forecast(self, source_agent: str, target_agent: str) -> dict[str, Any]:
        return await self._get(
            "/api/v1/forecast",
            {"source_agent": source_agent, "target_agent": target_agent},
        )

    async def forecast_trace(self, trace_id: str) -> list[dict[str, Any]]:
        data = await self._get("/api/v1/forecast/trace", {"trace_id": trace_id})
        return data.get("forecasts", [])

    async def attribute(self, trace_id: str, span_id: str) -> dict[str, Any]:
        return await self._get("/api/v1/attribution", {"trace_id": trace_id, "span_id": span_id})

    async def outcome_tracker_status(self) -> dict[str, Any]:
        return await self._get("/api/v1/outcome-tracker")

    @staticmethod
    def from_config(base_url: str | None = None, api_key: str | None = None) -> AgentICUClient:
        """Build a client from config.yaml + env, with explicit overrides."""
        from agenticu.api.config import load_config

        cfg = load_config()
        api_cfg = cfg.get("agenticu", {}).get("api", {})
        host = api_cfg.get("host", "localhost")
        if host == "0.0.0.0":
            host = "localhost"
        url = base_url or f"http://{host}:{api_cfg.get('port', 8000)}"
        key = api_key if api_key is not None else api_cfg.get("api_key", "")
        return AgentICUClient(base_url=url, api_key=key or "")
