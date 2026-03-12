"""
agents/tools/files.py — Research file I/O tools

Files are stored in the Railway PostgreSQL database (research_files table) as
the primary store, with a local research/ directory used as a write-through
cache for the current session.

Schema:
    research_files (id SERIAL, filename VARCHAR UNIQUE, content TEXT,
                    created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ)

Tools:
    read_research_file(filename)           — Read from DB (fallback: local cache)
    write_research_file(filename, content) — Write to DB + local cache
"""

import pathlib
from agents._sdk import function_tool

# Local cache directory alongside this file's project root
_RESEARCH_DIR = pathlib.Path(__file__).parents[2] / "research"


def _strip_prefix(filename: str) -> str:
    """Strip accidental research/ prefix that models sometimes add."""
    if filename.startswith("research/"):
        filename = filename[len("research/"):]
    return filename


def _safe_local_path(filename: str) -> pathlib.Path:
    """Return a resolved path under research/, raising ValueError on traversal."""
    _RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    resolved = (_RESEARCH_DIR / filename).resolve()
    if not str(resolved).startswith(str(_RESEARCH_DIR.resolve())):
        raise ValueError(f"Path traversal attempt blocked: {filename}")
    return resolved


@function_tool
async def read_research_file(filename: str) -> str:
    """Read a research file from the database.

    Args:
        filename: Bare filename (e.g. '2026-02-22-quantum.md'). Do NOT include a research/ prefix.
    """
    filename = _strip_prefix(filename)

    # Primary: database
    try:
        from agents.db import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT content FROM research_files WHERE filename = $1",
                filename,
            )
        if row:
            return row["content"]
    except Exception:
        pass  # Fall through to local cache

    # Fallback: local cache
    try:
        path = _safe_local_path(filename)
        if path.exists():
            return path.read_text(encoding="utf-8")
    except ValueError:
        pass

    return f"File not found: {filename}"


@function_tool
async def write_research_file(filename: str, content: str) -> str:
    """Write a research file to the database (and local cache).

    Args:
        filename: Bare filename (e.g. '2026-02-22-quantum.md'). Do NOT include a research/ prefix.
        content: The full content to write.
    """
    filename = _strip_prefix(filename)

    # Primary: database (upsert)
    db_ok = False
    try:
        from agents.db import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO research_files (filename, content, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (filename)
                DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
                """,
                filename,
                content,
            )
        db_ok = True
    except Exception as exc:
        db_ok = False
        db_error = str(exc)

    # Secondary: local cache (always write so agents can read back in same session)
    try:
        path = _safe_local_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except (ValueError, OSError):
        pass

    if db_ok:
        return f"Saved: {filename}"
    else:
        return f"Saved locally (DB error: {db_error}): {filename}"
