"""Database selection and explicit schema migrations."""

from __future__ import annotations

import asyncio
import re
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, closing
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

from agenticu.collector.storage import TraceStore

_LEDGER = """
CREATE TABLE IF NOT EXISTS agenticu_migrations (version TEXT PRIMARY KEY)
"""


class SQLitePool:
    """Execute the store's numbered SQL queries on a local SQLite database."""

    def __init__(self, path: str):
        self.path = path

    def _run(self, operation: Callable, sql: str, args: Any) -> Any:
        query = re.sub(r"\$(\d+)", r":\1", sql)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.row_factory = sqlite3.Row
            return operation(connection, query, args)

    async def execute(self, sql: str, *args: Any) -> None:
        await asyncio.to_thread(self._run, self._execute, sql, args)

    async def executemany(self, sql: str, args: list[tuple]) -> None:
        await asyncio.to_thread(self._run, self._executemany, sql, args)

    async def fetch(self, sql: str, *args: Any) -> list[dict]:
        return await asyncio.to_thread(self._run, self._fetch, sql, args)

    async def fetchrow(self, sql: str, *args: Any) -> dict | None:
        rows = await self.fetch(sql, *args)
        return rows[0] if rows else None

    @staticmethod
    def _parameters(args: tuple) -> dict[str, Any]:
        return {
            str(index): value.isoformat() if isinstance(value, datetime) else value
            for index, value in enumerate(args, 1)
        }

    @classmethod
    def _execute(cls, connection: sqlite3.Connection, query: str, args: tuple) -> None:
        connection.execute(query, cls._parameters(args))

    @classmethod
    def _executemany(cls, connection: sqlite3.Connection, query: str, args: list[tuple]) -> None:
        connection.executemany(query, map(cls._parameters, args))

    @classmethod
    def _fetch(cls, connection: sqlite3.Connection, query: str, args: tuple) -> list[dict]:
        return [dict(row) for row in connection.execute(query, cls._parameters(args))]


async def _check_schema(pool: Any, dialect: str) -> None:
    try:
        rows = await pool.fetch("SELECT version FROM agenticu_migrations")
    except Exception as exc:
        if isinstance(exc, sqlite3.OperationalError) and "no such table" in str(exc):
            raise RuntimeError("Database schema is missing. Run agenticu migrate.") from exc
        if getattr(exc, "sqlstate", None) == "42P01":
            raise RuntimeError("Database schema is missing. Run agenticu migrate.") from exc
        raise
    if {row["version"] for row in rows} != {item.name for item in _migrations(dialect)}:
        raise RuntimeError(
            "Database schema version differs from this release. Run agenticu migrate."
        )


@asynccontextmanager
async def open_store(config: dict[str, Any]) -> AsyncIterator[TraceStore]:
    """Open the configured store for the lifetime of the server."""
    if dsn := config.get("dsn"):
        import asyncpg

        async with asyncpg.create_pool(
            dsn,
            min_size=1,
            max_size=config.get("pool_size", 10),
            password=config.get("password") or None,
        ) as pool:
            await _check_schema(pool, "postgres")
            yield TraceStore(pool)
    elif path := config.get("sqlite_path"):
        if not Path(path).is_file():
            raise RuntimeError("SQLite database is missing. Run agenticu migrate.")
        pool = SQLitePool(path)
        await _check_schema(pool, "sqlite")
        yield TraceStore(pool)
    else:
        yield TraceStore()


def _migrations(dialect: str):
    directory = files("agenticu").joinpath("migrations", dialect)
    return sorted(
        (item for item in directory.iterdir() if item.name.endswith(".sql")),
        key=lambda item: item.name,
    )


def _migrate_sqlite(path: str) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(_LEDGER)
        versions = {row[0] for row in connection.execute("SELECT version FROM agenticu_migrations")}
        for migration in _migrations("sqlite"):
            if migration.name not in versions:
                for statement in migration.read_text().split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute("INSERT INTO agenticu_migrations VALUES (?)", (migration.name,))


async def migrate_store(config: dict[str, Any], schema_path: str | None = None) -> None:
    """Apply pending migrations transactionally. A custom schema is PostgreSQL-only."""
    if dsn := config.get("dsn"):
        import asyncpg

        connection = await asyncpg.connect(dsn, password=config.get("password") or None)
        try:
            async with connection.transaction():
                if schema_path:
                    await connection.execute(Path(schema_path).read_text())
                    return
                await connection.execute("SELECT pg_advisory_xact_lock(721448522)")
                await connection.execute(_LEDGER)
                versions = {
                    row["version"]
                    for row in await connection.fetch("SELECT version FROM agenticu_migrations")
                }
                for migration in _migrations("postgres"):
                    if migration.name not in versions:
                        await connection.execute(migration.read_text())
                        await connection.execute(
                            "INSERT INTO agenticu_migrations VALUES ($1)", migration.name
                        )
        finally:
            await connection.close()
    elif schema_path:
        raise ValueError("--schema requires a PostgreSQL DSN")
    elif path := config.get("sqlite_path"):
        await asyncio.to_thread(_migrate_sqlite, path)
