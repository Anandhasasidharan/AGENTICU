from __future__ import annotations

import asyncio

from agenticu import trace
from agenticu.classification.classifier import Classifier
from agenticu.collector.storage import TraceStore


class UnstableTool:
    """Simulates a flaky tool that fails on the first call."""

    def __init__(self):
        self._attempts = 0

    async def call(self, query: str) -> str:
        self._attempts += 1
        if self._attempts == 1:
            raise ValueError("Tool timeout — DB connection pool exhausted")
        return f"Result for: {query}"


class ApiClient:
    """Simulates an API that returns malformed data once."""

    def __init__(self):
        self._calls = 0

    async def fetch(self, endpoint: str) -> dict:
        self._calls += 1
        if self._calls <= 3:
            raise RuntimeError(f"Non-retryable: response 500 from {endpoint}")
        return {"status": "ok", "data": {"price": 42}}


@trace(
    agent_id="researcher",
    classifier=Classifier(fast_path_only=True),
    store=TraceStore(),
)
async def search_with_retry(query: str) -> str:
    tool = UnstableTool()
    return await tool.call(query)


@trace(
    agent_id="api-consumer",
    classifier=Classifier(fast_path_only=True),
    store=TraceStore(),
    max_retries=4,
)
async def fetch_with_recovery():
    client = ApiClient()
    return await client.fetch("/api/v2/prices")


async def main():
    print("=== Demo 1: tool timeout — auto-recovered ===")
    result = await search_with_retry("multi-agent LLM failures")
    print(f"  Result: {result}")

    print("\n=== Demo 2: API returns 500 three times then succeeds ===")
    result2 = await fetch_with_recovery()
    print(f"  Result: {result2}")


if __name__ == "__main__":
    asyncio.run(main())
