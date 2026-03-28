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
from functools import lru_cache

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
        # Derive SSL setting from the URL:
        #   - sslmode=require/verify-ca/verify-full  → ssl="require"
        #   - sslmode=disable or internal Railway URL → ssl=False
        #   - no sslmode param                       → ssl=False (TCP proxy default)
        from urllib.parse import urlparse, parse_qs
        _parsed = urlparse(database_url)
        _qs = parse_qs(_parsed.query)
        _sslmode = (_qs.get("sslmode") or [""])[0].lower()
        _internal = ".railway.internal" in (_parsed.hostname or "")
        if _sslmode in ("require", "verify-ca", "verify-full"):
            _ssl: object = "require"
        elif _sslmode == "disable" or _internal or not _sslmode:
            _ssl = False
        else:
            _ssl = False

        _pool = await asyncpg.create_pool(
            database_url,
            min_size=1,
            max_size=5,
            command_timeout=30,
            ssl=_ssl,
            init=_setup_vector_codec,
        )
        # Ensure HNSW index exists (idempotent — safe to run every startup)
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS embeddings_hnsw_idx
                    ON embeddings USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                """
            )
    return _pool


async def close_pool() -> None:
    """Close the connection pool. Call on graceful shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
