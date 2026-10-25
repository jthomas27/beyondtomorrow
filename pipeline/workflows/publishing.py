"""Publishing workflow implementation."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from time import monotonic

from pipeline.paths import PROJECT_ROOT
from pipeline.workflows.common import _AGENT_TIMEOUT, _STAGE_COOLDOWN, _RETRY_BACKOFF_BASE

logger = logging.getLogger("pipeline")


async def confirmed_publication(filename: str) -> dict:
    """Use the tool's durable receipt, never an LLM's claimed publication URL."""
    import json
    from pipeline.db import get_pool
    from pipeline.storage.deliveries import job_key
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT external_id,data FROM pipeline_deliveries WHERE channel='ghost' "
        "AND article_key=$1 AND recipient_key='' AND status='sent'",
        job_key.get() or 'file:' + filename,
    )
    if not row:
        raise RuntimeError('No confirmed Ghost publication receipt; downstream delivery blocked')
    post = json.loads(row['data']) if isinstance(row['data'], str) else row['data']
    from urllib.parse import urlsplit
    expected = urlsplit(os.environ.get('GHOST_URL', ''))
    actual = urlsplit(post.get('url', ''))
    if not row['external_id'] or post.get('status') != 'published' or not expected.netloc or actual.netloc != expected.netloc or actual.scheme != expected.scheme:
        raise RuntimeError('Ghost receipt does not confirm a live article on the configured site')
    return post



def _build_publish_input(filename: str) -> str:
    """Build the Publisher agent prompt for a given edited markdown filename."""
    return (
        f"Publish the blog post file '{filename}' to Ghost.\n"
        f"Step 1: call pick_random_asset_image()\n"
        f"Step 2: call upload_image_to_ghost(image_path=<path from step 1>)\n"
        f"Step 3: call publish_file_to_ghost(filename='{filename}', "
        f"feature_image_url=<url from step 2>, status='published')\n"
        f"Step 4: return EXACTLY: PUBLISHED: <ghost_url from step 3> | FEATURE_IMAGE: <url from step 2>"
    )

def _parse_publish_output(publish_output: str) -> tuple[str, str]:
    """Extract (ghost_url, feature_image_url) from publisher agent output.

    Returns ('', '') if not parseable.
    """
    import re as _re
    ghost_url = ""
    feature_image_url = ""
    # Look for PUBLISHED: <url> marker first (structured format)
    m = _re.search(r'PUBLISHED:\s*(https://[^\s|]+)', publish_output, _re.IGNORECASE)
    if m:
        ghost_url = m.group(1).rstrip("/") + "/"
    else:
        # Fallback: any beyondtomorrow.world URL
        m = _re.search(r'(https://beyondtomorrow\.world/[^\s|]+)', publish_output)
        if m:
            ghost_url = m.group(1)
    # Feature image
    m = _re.search(r'FEATURE_IMAGE:\s*(https://[^\s|\n]+)', publish_output, _re.IGNORECASE)
    if m:
        feature_image_url = m.group(1)
    else:
        # Fallback: look for feature_image in publish_file_to_ghost return embedded in output
        m = _re.search(r'feature[_-]?image:\s*(https://[^\s|\n]+)', publish_output, _re.IGNORECASE)
        if m:
            feature_image_url = m.group(1)
    return ghost_url, feature_image_url

async def _linkedin_post_direct(
    ghost_url: str,
    feature_image_url: str,
    edited_path,
    run_log=None,
) -> str:
    """Post a published Ghost article to LinkedIn by reading frontmatter directly.

    Called from main.py after the publisher step — keeps the LLM out of the
    LinkedIn loop entirely so excerpt/tags are always read from the actual file.
    Returns the LinkedIn result string.
    """
    from pathlib import Path
    from pipeline.tools.linkedin import _post_to_linkedin_impl
    from pipeline.tools.ghost import _parse_frontmatter

    try:
        raw = Path(edited_path).read_text(encoding="utf-8")
        meta, _ = _parse_frontmatter(raw)
    except Exception as exc:
        logger.warning("LinkedIn direct: could not read frontmatter from %s: %s", edited_path, exc)
        return f"SKIPPED: could not read frontmatter — {exc}"

    title = meta.get("title", "").strip()
    excerpt = meta.get("excerpt", "").strip()
    tags = meta.get("tags", "").strip()

    if not title or not excerpt:
        logger.warning("LinkedIn direct: missing title or excerpt in frontmatter — skipping.")
        return "SKIPPED: missing title or excerpt in frontmatter"

    logger.info("LinkedIn direct: posting '%s' → %s", title, ghost_url)
    try:
        result = await _post_to_linkedin_impl(
            title=title,
            excerpt=excerpt,
            post_url=ghost_url,
            tags=tags,
            feature_image_url=feature_image_url,
        )
    except Exception as exc:
        result = f"Error: {exc}"
        logger.error("LinkedIn direct: unexpected error: %s", exc)

    logger.info("LinkedIn direct result: %s", result)
    if run_log:
        run_log.stage_ok("LinkedIn", url=ghost_url, result=result)
    return result
