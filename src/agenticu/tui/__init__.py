"""Terminal UI (TUI) for AgentICU — full ops console.

Run with ``agenticu tui`` or ``python -m agenticu.tui``.
Requires the ``tui`` extra: ``pip install agenticu[tui]``.
"""

from agenticu.tui.client import AgentICUClient

__all__ = ["AgentICUClient"]
