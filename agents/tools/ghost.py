"""
agents/tools/ghost.py — Ghost CMS publishing tool

Publishes blog posts to Ghost via the Admin API using JWT authentication.

Required env vars:
    GHOST_URL       — Site URL, e.g. https://beyondtomorrow.world
    GHOST_ADMIN_KEY — Admin API key in id:secret format (from Ghost Admin → Integrations)
"""

import os
import re
import time
import httpx
import jwt
import markdown as md_lib
from agents._sdk import function_tool


def _make_ghost_token() -> str:
    """Generate a short-lived Ghost Admin JWT."""
    admin_key = os.environ.get("GHOST_ADMIN_KEY", "")
    if ":" not in admin_key:
        raise ValueError("GHOST_ADMIN_KEY must be in 'id:secret' format.")
    key_id, secret = admin_key.split(":", 1)
    iat = int(time.time())
    header = {"alg": "HS256", "typ": "JWT", "kid": key_id}
    payload = {"iat": iat, "exp": iat + 300, "aud": "/admin/"}
    return jwt.encode(
        payload, bytes.fromhex(secret), algorithm="HS256", headers=header
    )


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body. Returns (meta dict, body)."""
    meta: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
            body = parts[2].strip()
    return meta, body


async def _post_to_ghost(post_payload: dict) -> str:
    """Send a post payload to the Ghost Admin API."""
    ghost_url = os.environ.get("GHOST_URL", "").rstrip("/")
    if not ghost_url:
        return "Error: GHOST_URL environment variable is not set."
    try:
        token = _make_ghost_token()
    except ValueError as exc:
        return f"Error: {exc}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{ghost_url}/ghost/api/admin/posts/?source=html",
                json={"posts": [post_payload]},
                headers={
                    "Authorization": f"Ghost {token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        return f"Failed to publish to Ghost: {exc}"
    post = resp.json()["posts"][0]
    return f"Published: '{post['title']}' → {post['url']} (status: {post['status']})"


@function_tool
async def publish_to_ghost(
    filename: str,
    status: str = "draft",
) -> str:
    """Publish a blog post to Ghost CMS by reading a Markdown file from the database.

    The file must have YAML frontmatter with at least a `title` field.
    Optional frontmatter fields: tags, excerpt, feature_image.

    Args:
        filename: Bare filename of the post in the research store (e.g. '2026-03-12-post.md').
                  Do NOT prefix with research/.
        status: 'draft' (default, for human review) or 'published' (live immediately).
    """
    # Read file from DB / local cache by calling the storage logic directly
    from agents.tools.files import _strip_prefix, _safe_local_path, _RESEARCH_DIR
    filename = _strip_prefix(filename)

    content = None
    # Primary: database
    try:
        from agents.db import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT content FROM research_files WHERE filename = $1", filename
            )
        if row:
            content = row["content"]
    except Exception:
        pass

    # Fallback: local cache
    if not content:
        try:
            path = _safe_local_path(filename)
            if path.exists():
                content = path.read_text(encoding="utf-8")
        except (ValueError, OSError):
            pass

    if not content:
        return f"Error: File not found: {filename}"

    meta, body = _parse_frontmatter(content)
    title = meta.get("title", filename)
    tags_str = meta.get("tags", "")
    excerpt = meta.get("excerpt", "")
    feature_image = meta.get("feature_image", "")

    # Convert Markdown body to HTML
    html_content = md_lib.markdown(body, extensions=["extra", "nl2br"])

    tag_list = [{"name": t.strip()} for t in tags_str.split(",") if t.strip()]
    post_payload: dict = {
        "title": title,
        "html": html_content,
        "tags": tag_list,
        "custom_excerpt": excerpt,
        "status": status,
    }
    if feature_image:
        post_payload["feature_image"] = feature_image

    return await _post_to_ghost(post_payload)
