from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("agenticu")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agenticu",
        description="AgentICU — Multi-Agent Observability & Auto-Recovery",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("server", help="Start the API server")
    sub.add_parser("check", help="Run health check against a running server")

    tui = sub.add_parser("tui", help="Launch the terminal UI ops console")
    tui.add_argument(
        "--server",
        default=None,
        help="AgentICU server URL (default: from config.yaml, e.g. http://localhost:8000)",
    )
    tui.add_argument(
        "--api-key",
        default=None,
        help="API key (default: from config.yaml)",
    )

    migrate = sub.add_parser("migrate", help="Apply database schema")
    migrate.add_argument(
        "--dsn",
        default=os.environ.get("AGENTICU__STORAGE__DSN", "postgresql://localhost:5432/agenticu"),
        help="PostgreSQL DSN",
    )
    migrate.add_argument(
        "--schema",
        default=None,
        help="Path to a schema.sql (default: the schema bundled with the package)",
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.command == "server":
        _run_server()
    elif args.command == "tui":
        _run_tui(server=args.server, api_key=args.api_key)
    elif args.command == "migrate":
        asyncio.run(_run_migrate(args.dsn, args.schema))
    elif args.command == "check":
        asyncio.run(_run_check())
    else:
        parser.print_help()
        sys.exit(1)


def _run_server() -> None:
    import uvicorn

    from agenticu.api.config import load_config
    from agenticu.api.routes import create_app
    from agenticu.attribution.causal_attributor import CausalAttributor
    from agenticu.classification.classifier import Classifier
    from agenticu.collector.storage import TraceStore
    from agenticu.forecast.forecaster import Forecaster
    from agenticu.forecast.outcome_tracker import OutcomeTracker
    from agenticu.forecast.transition_model import TransitionModel
    from agenticu.recovery.playbook_runner import PlaybookRunner
    from agenticu.recovery.recovery_metrics import MetricsTracker

    cfg = load_config()
    api_cfg = cfg["agenticu"]["api"]

    store = TraceStore()
    metrics = MetricsTracker()
    runner = PlaybookRunner(store=store, metrics=metrics)
    transition_model = TransitionModel()
    classifier = Classifier(fast_path_only=True)
    forecaster = Forecaster(model=transition_model)
    attributor = CausalAttributor(store=store)
    tracker = OutcomeTracker(
        store=store,
        transition_model=transition_model,
        classifier=classifier,
        interval_secs=60,
        min_new_traces=5,
    )
    app = create_app(
        store=store,
        runner=runner,
        metrics=metrics,
        cors_origins=api_cfg.get("cors_origins", ["http://localhost:3000"]),
        api_key=api_cfg.get("api_key", ""),
        attributor=attributor,
        forecaster=forecaster,
        outcome_tracker=tracker,
    )

    logger.info("Starting AgentICU server on %s:%s", api_cfg["host"], api_cfg["port"])
    uvicorn.run(app, host=api_cfg["host"], port=api_cfg["port"], log_level="info")


async def _run_migrate(dsn: str, schema_path: str | None) -> None:
    try:
        import asyncpg
    except ImportError:
        logger.error("asyncpg is required. Install: pip install agenticu[postgres]")
        sys.exit(1)

    if schema_path:
        path = Path(schema_path)
        if not path.exists():
            logger.error("Schema file not found: %s", schema_path)
            sys.exit(1)
        sql = path.read_text()
    else:
        from importlib.resources import files

        sql = (files("agenticu") / "schema.sql").read_text()

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(sql)
        logger.info("Schema applied successfully")
    finally:
        await conn.close()


def _run_tui(server: str | None, api_key: str | None) -> None:
    try:
        import textual  # noqa: F401
    except ImportError:
        logger.error("textual is required. Install: pip install agenticu[tui]")
        sys.exit(1)

    from agenticu.tui.app import AgentICUApp
    from agenticu.tui.client import AgentICUClient

    client = AgentICUClient.from_config(base_url=server, api_key=api_key)
    logger.info("Launching TUI against %s", client.base_url)
    AgentICUApp(base_url=client.base_url, api_key=client.api_key).run()


async def _run_check() -> None:
    import httpx

    host = os.environ.get("AGENTICU__API__HOST", "localhost")
    port = os.environ.get("AGENTICU__API__PORT", "8000")
    url = f"http://{host}:{port}/health"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=5)
            resp.raise_for_status()
            print(f"OK — {resp.json()}")
    except Exception as e:
        print(f"FAIL — {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
