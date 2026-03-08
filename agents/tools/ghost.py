"""
agents/tools/ghost.py — Ghost CMS publishing tool

Publishes blog posts to Ghost via the Admin API using JWT authentication.

Required env vars:
    GHOST_URL       — Site URL, e.g. https://beyondtomorrow.world
    GHOST_ADMIN_KEY — Admin API key in id:secret format (from Ghost Admin → Integrations)
"""

import os
import time
import httpx
import jwt
from agents._sdk import function_tool


@function_tool
async def publish_to_ghost(
    title: str,
    html_content: str,
    tags: str = "",
    excerpt: str = "",
    status: str = "draft",
) -> str:
    """Publish a blog post to Ghost CMS via the Admin API.

    Args:
        title: The blog post title.
        html_content: The post content in HTML format.
        tags: Comma-separated list of tag names (e.g. "technology, AI, quantum").
        excerpt: A short custom excerpt for the post (1-2 sentences).
        status: Publication status — 'draft' (default, for review) or 'published' (live immediately).
    """
    ghost_url = os.environ.get("GHOST_URL", "").rstrip("/")
    admin_key = os.environ.get("GHOST_ADMIN_KEY", "")

    if not ghost_url or not admin_key:
        return "Error: GHOST_URL and GHOST_ADMIN_KEY environment variables must be set."

    if ":" not in admin_key:
        return "Error: GHOST_ADMIN_KEY must be in 'id:secret' format."

    key_id, secret = admin_key.split(":", 1)
    iat = int(time.time())
    header = {"alg": "HS256", "typ": "JWT", "kid": key_id}
    payload = {"iat": iat, "exp": iat + 300, "aud": "/admin/"}

    try:
        token = jwt.encode(
            payload,
            bytes.fromhex(secret),
            algorithm="HS256",
            headers=header,
        )
    except Exception as exc:
        return f"Error generating Ghost JWT: {exc}"

    tag_list = (
        [{"name": t.strip()} for t in tags.split(",") if t.strip()]
        if tags
        else []
    )
    post_data = {
        "posts": [
            {
                "title": title,
                "html": html_content,
                "tags": tag_list,
                "custom_excerpt": excerpt,
                "status": status,
            }
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{ghost_url}/ghost/api/admin/posts/",
                json=post_data,
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
