from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

import httpx

from agenticu.models import FailureMode, Span

logger = logging.getLogger(__name__)


class EscalationService:
    """Human-in-the-loop escalation via webhooks.

    Supports Slack and PagerDuty. Extend via add_hook().
    """

    def __init__(
        self, slack_webhook: str = "", pagerduty_key: str = "", pagerduty_service_id: str = ""
    ):
        self.slack_webhook = slack_webhook
        self.pagerduty_key = pagerduty_key
        self.pagerduty_service_id = pagerduty_service_id
        self._custom_hooks: list[Any] = []

    def add_hook(self, hook: Any) -> None:
        self._custom_hooks.append(hook)

    async def __call__(
        self,
        *,
        span: Span,
        failure_mode: FailureMode,
        reason: str,
        root_agent_id: str | None = None,
        trace: list[Span] | None = None,
    ) -> None:
        payload = self._build_payload(span, failure_mode, reason, root_agent_id)
        if trace is not None:
            payload["trace"] = json.loads(json.dumps([asdict(item) for item in trace], default=str))
        logger.warning("Escalating trace %s mode %s: %s", span.trace_id, failure_mode.value, reason)

        try:
            if self.slack_webhook:
                await self._send_slack(payload)
        except httpx.HTTPError:
            logger.exception("Slack escalation delivery failed")
        try:
            if self.pagerduty_key:
                await self._send_pagerduty(payload)
        except httpx.HTTPError:
            logger.exception("PagerDuty escalation delivery failed")

        for hook in self._custom_hooks:
            try:
                await hook(payload)
            except Exception:
                logger.exception("Custom escalation hook failed")

    def _build_payload(
        self,
        span: Span,
        failure_mode: FailureMode,
        reason: str,
        root_agent_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "trace_id": span.trace_id,
            "span_id": span.span_id,
            "agent_id": span.agent_id,
            "root_agent_id": root_agent_id or span.agent_id,
            "failure_mode": failure_mode.value,
            "failure_name": failure_mode.name,
            "reason": reason,
            "error": span.error_message,
            "span_type": span.span_type,
        }

    async def _send_slack(self, payload: dict[str, Any]) -> None:
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🚨 AgentICU Escalation: {payload['failure_name']}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Agent:* `{payload['agent_id']}`"},
                    {"type": "mrkdwn", "text": f"*Trace:* `{payload['trace_id'][:8]}...`"},
                    {"type": "mrkdwn", "text": f"*Mode:* `{payload['failure_mode']}`"},
                    {"type": "mrkdwn", "text": f"*Reason:* {payload['reason']}"},
                ],
            },
        ]
        if payload.get("error"):
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Error:* ```{payload['error'][:500]}```",
                    },
                }
            )

        async with httpx.AsyncClient() as client:
            response = await client.post(self.slack_webhook, json={"blocks": blocks})
            response.raise_for_status()
            if "trace" in payload:
                trace = json.dumps(payload["trace"], ensure_ascii=True)
                chunks = [trace[start : start + 2400] for start in range(0, len(trace), 2400)]
                for index, chunk in enumerate(chunks, 1):
                    response = await client.post(
                        self.slack_webhook,
                        json={
                            "text": f"Trace {payload['trace_id']} ({index}/{len(chunks)})\n{chunk}"
                        },
                    )
                    response.raise_for_status()

    async def _send_pagerduty(self, payload: dict[str, Any]) -> None:
        body = {
            "routing_key": self.pagerduty_key,
            "event_action": "trigger",
            "payload": {
                "summary": f"AgentICU: {payload['failure_name']} on {payload['agent_id']}",
                "severity": "error",
                "source": payload["agent_id"],
                "custom_details": payload,
            },
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://events.pagerduty.com/v2/enqueue",
                json=body,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
