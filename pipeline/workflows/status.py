"""Status workflow implementation."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from time import monotonic

from pipeline.paths import PROJECT_ROOT
from pipeline.workflows.common import _AGENT_TIMEOUT, _STAGE_COOLDOWN, _RETRY_BACKOFF_BASE

logger = logging.getLogger("pipeline")



async def _check_status() -> None:
    """Check environment, database connection, and print a status report."""
    logger.info("BeyondTomorrow.World — Agent Status")
    logger.info("=" * 40)

    # Check env vars
    checks = [
        ("OPENAI_API_KEY", "OpenAI API access"),
        ("DATABASE_URL", "pgvector knowledge corpus"),
        ("GHOST_URL", "Ghost CMS publishing"),
        ("GHOST_ADMIN_KEY", "Ghost Admin API"),
    ]
    all_ok = True
    for var, desc in checks:
        val = os.environ.get(var)
        if val:
            logger.info("  ✓ %s %s (set)", f"{var:<20}", desc)
        else:
            logger.error("  ✗ %s %s — NOT SET", f"{var:<20}", desc)
            all_ok = False

    # LinkedIn cross-posting (optional — non-blocking)
    from datetime import date as _date
    li_token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()
    li_urn = os.environ.get("LINKEDIN_PERSON_URN", "").strip()
    li_expires = os.environ.get("LINKEDIN_TOKEN_EXPIRES", "").strip()
    if li_token and li_urn:
        expiry_info = ""
        if li_expires:
            try:
                days_left = (_date.fromisoformat(li_expires) - _date.today()).days
                if days_left <= 0:
                    expiry_info = f" ⚠️  TOKEN EXPIRED on {li_expires} — re-run scripts/linkedin_auth.py"
                elif days_left <= 7:
                    expiry_info = f" ⚠️  expires in {days_left}d on {li_expires} — refresh soon"
                else:
                    expiry_info = f" (expires {li_expires}, {days_left}d remaining)"
            except ValueError:
                expiry_info = f" (LINKEDIN_TOKEN_EXPIRES invalid: {li_expires!r})"
        else:
            expiry_info = " (expiry unknown — re-run scripts/linkedin_auth.py to set LINKEDIN_TOKEN_EXPIRES)"
        logger.info("  ✓ %-20s LinkedIn cross-posting%s", "LINKEDIN_ACCESS_TOKEN", expiry_info)
    else:
        logger.info("  - %-20s LinkedIn not configured (optional — pipeline will skip cross-posting)", "LINKEDIN")

    # Check database connection
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        try:
            from pipeline.db import get_pool

            pool = await get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS n FROM embeddings"
                )
            logger.info("  ✓ Database connected — %s embeddings in corpus", f"{row['n']:,}")
        except Exception as exc:
            logger.error("  ✗ Database connection failed: %s", exc)
            all_ok = False
    else:
        logger.error("  ✗ Database check skipped — DATABASE_URL not set")

    if all_ok:
        logger.info("Status: READY ✓")
    else:
        logger.error("Status: NOT READY — fix the issues above before running agents")
