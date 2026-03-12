"""
agents/setup.py — SDK initialisation using GitHub Models API

Call init_github_models() once at startup (from agents/main.py or wherever
the agent runner is invoked). After that, all Agent definitions in
agents/definitions.py will use this client automatically.

Required env var:
    GITHUB_TOKEN — Fine-grained PAT with models:read scope
"""

import os
from openai import AsyncOpenAI
from agents._sdk import set_default_openai_client, set_default_openai_api


def init_github_models() -> AsyncOpenAI:
    """Configure the OpenAI Agents SDK to use GitHub Models API.

    Returns the AsyncOpenAI client so callers can inspect it if needed.
    Raises RuntimeError if GITHUB_TOKEN is not set.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN environment variable is not set. "
            "Create a fine-grained GitHub PAT with 'models:read' scope "
            "and set it in your Railway environment variables."
        )

    client = AsyncOpenAI(
        base_url="https://models.github.ai/inference",
        api_key=token,
    )
    set_default_openai_client(client)
    set_default_openai_api("chat_completions")
    return client


async def ensure_db_schema() -> None:
    """Create any missing tables on first run. Safe to call on every startup."""
    try:
        from agents.db import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS research_files (
                    id          SERIAL PRIMARY KEY,
                    filename    VARCHAR(500) UNIQUE NOT NULL,
                    content     TEXT NOT NULL,
                    created_at  TIMESTAMPTZ DEFAULT NOW(),
                    updated_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS research_files_filename_idx
                ON research_files (filename)
            """)
    except Exception:
        pass  # Non-fatal: DB may not be available in all environments
