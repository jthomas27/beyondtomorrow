"""Explicit PostgreSQL migrations. Default: print the plan; --apply writes."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

from pipeline.paths import PROJECT_ROOT

MIGRATIONS = PROJECT_ROOT / "infra" / "migrations" / "postgres"


async def apply_migrations(connection, directory: Path = MIGRATIONS) -> list[str]:
    """Apply new files atomically; reject changes to already-applied files."""
    applied = []
    async with connection.transaction():
        await connection.execute("SELECT pg_advisory_xact_lock($1)", 87260424)
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS pipeline_schema_migrations ("
            "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
            "applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
        )
        for path in sorted(directory.glob("*.sql")):
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            previous = await connection.fetchval(
                "SELECT checksum FROM pipeline_schema_migrations WHERE version=$1", path.name
            )
            if previous is not None:
                if previous != checksum:
                    raise RuntimeError(f"Applied migration was modified: {path.name}")
                continue
            await connection.execute(sql)
            await connection.execute(
                "INSERT INTO pipeline_schema_migrations(version, checksum) VALUES ($1, $2)",
                path.name, checksum,
            )
            applied.append(path.name)
    return applied


async def _apply() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    from pipeline.storage.postgres import ssl_for_url
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    connection = await asyncpg.connect(url, ssl=ssl_for_url(url), command_timeout=120)
    try:
        for name in await apply_migrations(connection):
            print(f"Applied {name}")
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            print(path.name)
        return
    try:
        asyncio.run(_apply())
    except Exception as exc:
        # Database/client exceptions can contain credential-bearing URLs.
        raise SystemExit(f"Migration failed ({type(exc).__name__}); details withheld") from None


if __name__ == "__main__":
    main()
