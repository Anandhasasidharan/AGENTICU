from __future__ import annotations

import sys

from agenticu.tui.app import AgentICUApp
from agenticu.tui.client import AgentICUClient


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    base_url = args[0] if args else None
    client = AgentICUClient.from_config(base_url=base_url)
    app = AgentICUApp(base_url=client.base_url, api_key=client.api_key)
    app.run()


if __name__ == "__main__":
    main()
