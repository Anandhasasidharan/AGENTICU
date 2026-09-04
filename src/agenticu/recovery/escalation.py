from __future__ import annotations

import logging
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
    ) -> None:
        payload = self._build_payload(span, failure_mode, reason, root_agent_id)

        if self.slack_webhook:
            await self._send_slack(payload)
        if self.pagerduty_key:
            await self._send_pagerduty(payload)

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
            await client.post(self.slack_webhook, json={"blocks": blocks})

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
            await client.post(
                "https://events.pagerduty.com/v2/enqueue",
                json=body,
                headers={"Content-Type": "application/json"},
            )
