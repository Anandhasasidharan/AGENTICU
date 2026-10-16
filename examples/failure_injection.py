"""Demo: inline auto-recovery from classified agent failures.

Two decorator-instrumented agents fail with behavioural signatures the MAST
classifier recognises. For every failure AgentICU runs the loop:

    classify failure mode -> pick a recovery playbook -> retry the call

Recovery only fires when the failure maps to one of the 14 MAST modes, so this
demo injects realistic *agent* failures (repetition, derailment) rather than
generic infrastructure errors.

Run:
    python examples/failure_injection.py
"""

from __future__ import annotations

import asyncio

from agenticu import trace
from agenticu.classification.classifier import Classifier
from agenticu.collector.storage import TraceStore


class RepetitiveAgent:
    """Agent that repeats its previous step once, then recovers."""

    def __init__(self) -> None:
        self._attempts = 0

    async def step(self, query: str) -> str:
        self._attempts += 1
        if self._attempts == 1:
            raise RuntimeError("agent is repeating the same step over and over")
        return f"Search results for: {query}"


class DerailingAgent:
    """Agent that keeps drifting off-topic before finally staying on task."""

    def __init__(self, fail_times: int) -> None:
        self._fail_times = fail_times
        self._calls = 0

    async def run(self, goal: str) -> str:
        self._calls += 1
        if self._calls <= self._fail_times:
            raise RuntimeError(
                "agent went off-topic and pursued an unrelated task objective"
            )
        return f"Completed: {goal}"


# State lives outside the decorated functions so it survives retries.
_repetitive_agent = RepetitiveAgent()
_derailing_agent = DerailingAgent(fail_times=3)

STORE = TraceStore()
CLASSIFIER = Classifier(fast_path_only=True)


@trace(agent_id="researcher", classifier=CLASSIFIER, store=STORE)
async def search_with_recovery(query: str) -> str:
    """Fails once with Step Repetition, is classified, recovered, retried."""
    return await _repetitive_agent.step(query)


@trace(agent_id="planner", classifier=CLASSIFIER, store=STORE, max_retries=4)
async def plan_with_recovery(goal: str) -> str:
    """Fails three times with Task Derailment; recovers on the fourth attempt."""
    return await _derailing_agent.run(goal)


async def main() -> None:
    print("=== Demo 1: step repetition — classified and auto-recovered ===")
    result = await search_with_recovery("multi-agent LLM failures")
    print(f"  Result: {result}")

    print("\n=== Demo 2: derails three times, recovers within max_retries=4 ===")
    result2 = await plan_with_recovery("summarise the price feed")
    print(f"  Result: {result2}")

    stats = await STORE.get_recovery_stats()
    print(
        f"\nRecovery attempts recorded: {stats['total']} "
        f"(succeeded: {stats['succeeded']}, failed: {stats['failed']})"
    )


if __name__ == "__main__":
    asyncio.run(main())
