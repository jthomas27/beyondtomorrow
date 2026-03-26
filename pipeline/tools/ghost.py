"""
agents/tools/ghost.py — Ghost CMS publishing tool

Publishes blog posts to Ghost via the Admin API using JWT authentication.

Required env vars:
    GHOST_URL       — Site URL, e.g. https://beyondtomorrow.world
    GHOST_ADMIN_KEY — Admin API key in id:secret format (from Ghost Admin → Integrations)
"""

import asyncio
import json as _json
import logging
import mimetypes
import os
import pathlib
import re
import time
import httpx
import jwt
import markdown as md_converter
from pipeline._sdk import function_tool

logger = logging.getLogger(__name__)

_GHOST_RETRY_ATTEMPTS = 3
_GHOST_RETRY_DELAYS = [2, 4, 8]  # seconds


def _build_lexical(html: str) -> str:
    """Wrap HTML in a Ghost Lexical HTML card (lossless)."""
    return _json.dumps({
        "root": {
            "children": [{"type": "html", "html": html}],
            "direction": None, "format": "", "indent": 0,
            "type": "root", "version": 1,
        }
    })


async def _ghost_post_with_retry(client: httpx.AsyncClient, url: str, json_data: dict, headers: dict) -> httpx.Response:
    """POST to Ghost Admin API with retry + exponential backoff."""
    last_exc: Exception | None = None
    for attempt in range(_GHOST_RETRY_ATTEMPTS):
        try:
            resp = await client.post(url, json=json_data, headers=headers)
            resp.raise_for_status()
            return resp
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < _GHOST_RETRY_ATTEMPTS - 1:
                delay = _GHOST_RETRY_DELAYS[attempt]
                logger.warning("Ghost API attempt %d failed (%s), retrying in %ds...", attempt + 1, exc, delay)
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]

_RESEARCH_DIR = pathlib.Path(__file__).parents[2] / "research"


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML-style frontmatter from a markdown string.

    Returns (metadata_dict, body_without_frontmatter).
    """
    meta: dict = {}
    if not text.startswith("---"):
        return meta, text
    end = text.find("\n---", 3)
    if end == -1:
        return meta, text
    fm_block = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    for line in fm_block.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, body


@function_tool
async def publish_to_ghost(
    title: str,
    html_content: str,
    tags: str = "",
    excerpt: str = "",
    status: str = "draft",
    feature_image: str = "",
) -> str:
    """Publish a blog post to Ghost CMS via the Admin API.

    Args:
        title: The blog post title.
        html_content: The post content in HTML format.
        tags: Comma-separated list of tag names (e.g. "technology, AI, quantum").
        excerpt: A short custom excerpt for the post (1-2 sentences).
        status: Publication status — 'draft' (default, for review) or 'published' (live immediately).
        feature_image: Optional URL for the post thumbnail/feature image.
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
    lexical = _build_lexical(html_content)
    post_payload: dict = {
        "title": title,
        "lexical": lexical,
        "tags": tag_list,
        "custom_excerpt": excerpt,
        "status": status,
    }
    if feature_image:
        post_payload["feature_image"] = feature_image

    post_data = {"posts": [post_payload]}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await _ghost_post_with_retry(
                client,
                f"{ghost_url}/ghost/api/admin/posts/",
                post_data,
                {"Authorization": f"Ghost {token}", "Content-Type": "application/json"},
            )
    except httpx.HTTPError as exc:
        return f"Failed to publish to Ghost: {exc}"

    post = resp.json()["posts"][0]
    return f"Published: '{post['title']}' → {post['url']} (status: {post['status']})"


@function_tool
async def upload_image_to_ghost(image_path: str) -> str:
    """Upload a local image file to Ghost CMS and return the hosted URL.

    Args:
        image_path: Absolute path to the image file to upload.

    Returns:
        The hosted URL of the uploaded image, or an error message.
    """
    ghost_url = os.environ.get("GHOST_URL", "").rstrip("/")
    admin_key = os.environ.get("GHOST_ADMIN_KEY", "")

    if not ghost_url or not admin_key:
        return "Error: GHOST_URL and GHOST_ADMIN_KEY environment variables must be set."

    if ":" not in admin_key:
        return "Error: GHOST_ADMIN_KEY must be in 'id:secret' format."

    path = pathlib.Path(image_path)
    if not path.exists():
        return f"Error: Image file not found: {image_path}"

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

    mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"

    try:
        with open(path, "rb") as f:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{ghost_url}/ghost/api/admin/images/upload/",
                    headers={"Authorization": f"Ghost {token}"},
                    files={"file": (path.name, f, mime_type)},
                    data={"purpose": "image"},
                )
                resp.raise_for_status()
    except httpx.HTTPError as exc:
        return f"Failed to upload image to Ghost: {exc}"

    data = resp.json()
    if "images" in data and data["images"]:
        return data["images"][0]["url"]
    return f"Error: Unexpected response from Ghost image upload: {data}"


@function_tool
async def publish_file_to_ghost(
    filename: str,
    feature_image_url: str = "",
    status: str = "published",
) -> str:
    """Read a markdown research file and publish it directly to Ghost CMS.

    This tool handles all conversion internally — the caller only needs to
    provide the filename (e.g. '2026-03-13-article-edited.md'), an optional
    feature image URL, and the publication status.

    Args:
        filename: Filename inside the research/ directory (e.g. '2026-03-13-article-edited.md').
        feature_image_url: Optional hosted URL for the post header image.
        status: 'published' (live) or 'draft'. Always use 'published'.
    """
    safe_path = (_RESEARCH_DIR / pathlib.Path(filename).name).resolve()
    if not str(safe_path).startswith(str(_RESEARCH_DIR.resolve())):
        return "Error: Path traversal detected — invalid filename."
    if not safe_path.exists():
        return f"Error: File not found in research/: {filename}"

    raw = safe_path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)

    title = meta.get("title", safe_path.stem.replace("-", " ").title())
    tags_str = meta.get("tags", "")
    excerpt = meta.get("excerpt", "")

    html_content = md_converter.markdown(
        body,
        extensions=["extra", "sane_lists"],
    )

    # --- Strip trailing editor artefacts after Just For Laughs ---
    # The Editor agent sometimes appends its rationale notes (separated by <hr>)
    # or reference lists after the joke.  Remove everything from the first <hr>
    # or extra heading that appears after the JFL section.
    _jfl_heading = re.search(r'<h2[^>]*>\s*Just For Laughs\s*</h2>', html_content, re.IGNORECASE)
    if _jfl_heading:
        _after = html_content[_jfl_heading.end():]
        _trail = re.search(r'<hr\s*/?>|<h[23][^>]*>', _after, re.IGNORECASE)
        if _trail:
            _plain_trail = re.sub(r'<[^>]+>', '', _after[_trail.start():]).strip()
            if _plain_trail:
                html_content = html_content[:_jfl_heading.end()] + _after[:_trail.start()]
    # --- End trailing artefact strip ---

    # --- Pre-publish validation ---
    # All items are required. Return MISSING: if any check fails so the
    # pipeline can resolve the problem before any API call is made.
    import re as _re_val
    missing: list[str] = []

    stripped_title = (title or "").strip()
    if not stripped_title:
        missing.append("title (missing or empty in frontmatter)")
    else:
        title_word_count = len(stripped_title.split())
        if title_word_count < 5 or title_word_count > 10:
            missing.append(
                f"title length ({title_word_count} words — must be 5–10 words, "
                "punchy, specific, and not misleading; rewrite it)"
            )

    plain_body = _re_val.sub(r"<[^>]+>", "", html_content).strip()
    word_count = len(plain_body.split())
    if word_count < 500:
        missing.append(
            f"body_content too short ({word_count} words) — "
            "post body must be at least 500 words"
        )

    if not (feature_image_url or "").strip().startswith("http"):
        missing.append(
            "feature_image (no hosted image URL provided — upload an image first)"
        )

    if not excerpt.strip():
        missing.append("excerpt (empty in frontmatter — add a 1–2 sentence summary)")

    # Must end with a "Just For Laughs" section
    if "just for laughs" not in body.lower():
        missing.append("'Just For Laughs' section (required at end of every post)")

    if missing:
        items = "; ".join(missing)
        return (
            f"MISSING: {items} — do not publish until all items are resolved. "
            "Fix the reported issue(s) in the upstream pipeline stage and retry."
        )
    # --- End pre-publish validation ---

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

    tag_list = [{"name": t.strip()} for t in tags_str.split(",") if t.strip()]
    lexical = _build_lexical(html_content)
    post_payload: dict = {
        "title": title,
        "lexical": lexical,
        "tags": tag_list,
        "custom_excerpt": excerpt,
        "status": status,
    }
    if feature_image_url:
        post_payload["feature_image"] = feature_image_url

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await _ghost_post_with_retry(
                client,
                f"{ghost_url}/ghost/api/admin/posts/",
                {"posts": [post_payload]},
                {"Authorization": f"Ghost {token}", "Content-Type": "application/json"},
            )
    except httpx.HTTPError as exc:
        return f"Failed to publish to Ghost: {exc}"

    post = resp.json()["posts"][0]
    return f"Published: '{post['title']}' → {post['url']} (status: {post['status']})"
