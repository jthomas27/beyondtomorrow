"""
agents/db.py — asyncpg connection pool for pgvector

Provides a singleton asyncpg pool that all agent tools share.
The pool is created on first call and reused for subsequent calls.

Required env var:
    DATABASE_URL — PostgreSQL connection string (public TCP proxy URL)
                   Set automatically by Railway when TCP proxy is enabled.
"""

import os
import asyncpg

_pool: asyncpg.Pool | None = None


async def _setup_vector_codec(conn: asyncpg.Connection) -> None:
    """Register pgvector text codec so Python list[float] can be passed directly.

    After registration, queries can pass vectors as Python lists without manual
    string construction — asyncpg encodes/decodes them automatically.
    """
    await conn.set_type_codec(
        "vector",
        encoder=lambda v: "[" + ",".join(str(x) for x in v) + "]",
        decoder=lambda v: list(map(float, v.strip("[]").split(","))),
        schema="public",
        format="text",
    )


async def get_pool() -> asyncpg.Pool:
    """Return the shared asyncpg connection pool, creating it if needed."""
    global _pool
    if _pool is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL environment variable is not set. "
                "Enable the TCP proxy on the pgvector Railway service "
                "to get a public connection URL."
            )
        from pipeline.storage.postgres import ssl_for_url

        _pool = await asyncpg.create_pool(
            database_url,
            min_size=1,
            max_size=5,
            command_timeout=30,
            ssl=ssl_for_url(database_url),
            init=_setup_vector_codec,
        )
    return _pool


async def close_pool() -> None:
    """Close the connection pool. Call on graceful shutdown."""
    global _pool
    from pipeline.storage.deliveries import job_key
    if job_key.get():
        # The email runner also uses this pool for its durable lease heartbeat.
        return
    if _pool is not None:
        await _pool.close()
        _pool = None
