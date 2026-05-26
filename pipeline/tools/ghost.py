"""
agents/tools/ghost.py — Ghost CMS publishing tool

Publishes blog posts to Ghost via the Admin API using JWT authentication.

Required env vars:
    GHOST_URL       — Site URL, e.g. https://beyondtomorrow.world
    GHOST_ADMIN_KEY — Admin API key in id:secret format (from Ghost Admin → Integrations)
"""

import asyncio
import html as _html
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
            # The LLM sometimes encodes '&' as the 3-byte sequence \x00 + "26"
            # (the hex value 0x26 for '&', prefixed with a null byte). Restoring it
            # then calling html.unescape() converts e.g. &mdash; → — in plain text.
            cleaned = _html.unescape(
                value.strip().replace("\x0026", "&").replace("\x00", "")
            )
            meta[key.strip()] = cleaned
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
    if status == "published":
        post_payload["email_recipient_filter"] = "free"
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


async def _fetch_published_slugs(ghost_url: str, admin_key: str) -> set[str] | None:
    """Return the set of all published post slugs from Ghost, or None on error.

    Used by the pre-publish cross-reference guardrail to detect hallucinated
    links to posts that don't actually exist.
    """
    if not ghost_url or ":" not in admin_key:
        return None
    key_id, secret = admin_key.split(":", 1)
    iat = int(time.time())
    try:
        token = jwt.encode(
            {"iat": iat, "exp": iat + 300, "aud": "/admin/"},
            bytes.fromhex(secret),
            algorithm="HS256",
            headers={"alg": "HS256", "typ": "JWT", "kid": key_id},
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{ghost_url}/ghost/api/admin/posts/"
                "?limit=all&fields=slug&filter=status:published",
                headers={"Authorization": f"Ghost {token}"},
            )
            r.raise_for_status()
            return {p["slug"] for p in r.json().get("posts", [])}
    except Exception as exc:
        logger.warning("Could not fetch published slugs for cross-reference check: %s", exc)
        return None


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
    # Apply comprehensive LLM punctuation sanitisation before any further processing.
    # Handles: \x0026 → &mdash; → —, \x0027 → ', \x1a → apostrophe/comma, &nbsp; → space.
    from pipeline.tools.files import _clean_llm_text
    raw = _clean_llm_text(raw)
    meta, body = _parse_frontmatter(raw)

    title = meta.get("title", safe_path.stem.replace("-", " ").title())
    tags_str = meta.get("tags", "")
    excerpt = meta.get("excerpt", "")
    meta_title = meta.get("meta_title", "")
    meta_description = meta.get("meta_description", "")
    image_alt = meta.get("image_alt", "") or title
    focus_keyword = meta.get("focus_keyword", "")

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

    # --- Excerpt guardrail — Ghost enforces a 300-char limit on custom_excerpt.
    # Auto-trim at a word boundary so publish is never blocked by excerpt length alone.
    _MAX_EXCERPT = 300
    if len(excerpt) > _MAX_EXCERPT:
        excerpt = excerpt[:_MAX_EXCERPT].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
        logger.info("Excerpt trimmed to %d chars to meet Ghost 300-char limit.", len(excerpt))

    # --- SEO field guardrails ---
    _MAX_META_TITLE = 60
    if len(meta_title) > _MAX_META_TITLE:
        meta_title = meta_title[:_MAX_META_TITLE].rsplit(" ", 1)[0].rstrip(".,;:")
        logger.info("meta_title trimmed to %d chars.", len(meta_title))
    _MAX_META_DESC = 160
    if len(meta_description) > _MAX_META_DESC:
        meta_description = meta_description[:_MAX_META_DESC].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
        logger.info("meta_description trimmed to %d chars.", len(meta_description))

    # Read Ghost credentials now so the cross-reference guardrail can use them.
    ghost_url = os.environ.get("GHOST_URL", "").rstrip("/")
    admin_key = os.environ.get("GHOST_ADMIN_KEY", "")

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

    if not focus_keyword.strip():
        logger.warning(
            "SEO: 'focus_keyword' missing in frontmatter for '%s' — "
            "add it to improve keyword targeting.",
            filename,
        )

    # Must end with a "Just For Laughs" section
    if "just for laughs" not in body.lower():
        missing.append("'Just For Laughs' section (required at end of every post)")

    # --- Formatting guardrails ---

    # (i) Case study callout label — must be integrated as prose, not a bold label
    if _re_val.search(r'\*\*[Cc]ase\s+[Ss]tudy:', body):
        missing.append(
            "formatting: '**Case study:**' label found — integrate as seamless prose "
            "(e.g. 'This played out at [Organisation], which in [year]...'). "
            "Remove the bold callout label."
        )

    # (ii) Empty list items — artefact of incomplete LLM generation
    if _re_val.search(r'<li>\s*</li>', html_content):
        missing.append(
            "formatting: one or more empty list items found — complete or remove them"
        )

    # (iii) Singleton lists — a list with exactly one item should be prose
    for _list_m in _re_val.finditer(r'<(ul|ol)>(.*?)</\1>', html_content, _re_val.DOTALL):
        if len(_re_val.findall(r'<li', _list_m.group(2))) == 1:
            _li_text = _re_val.sub(r'<[^>]+>', '', _list_m.group(2)).strip()[:60]
            missing.append(
                f"formatting: single-item list found ('{_li_text}') — "
                "convert to prose or add more items (lists need \u2265 3 items)"
            )
            break

    # (iv) Rogue/orphaned paragraphs — <p> with 1–2 words ending in ':' are stray labels
    for _p_m in _re_val.finditer(r'<p>(.*?)</p>', html_content, _re_val.DOTALL):
        _p_text = _re_val.sub(r'<[^>]+>', '', _p_m.group(1)).strip()
        _p_words = _p_text.split()
        if 0 < len(_p_words) <= 2 and _p_text.endswith(':'):
            missing.append(
                f"formatting: rogue paragraph label found ('{_p_text}') — "
                "remove this orphaned label or complete the thought"
            )
            break

    # (v) "Pause and think" — a writer's stage direction that must never appear
    # as literal prose. The LLM sometimes writes "Pause and think:" verbatim,
    # which reads as an awkward meta-comment rather than engaging narrative.
    _pause_re = _re_val.compile(r'\bpause\s+and\s+think\b', _re_val.IGNORECASE)
    _pause_matches = _pause_re.findall(plain_body)
    if _pause_matches:
        missing.append(
            f"prose phrase: 'Pause and think' found {len(_pause_matches)} time(s) — "
            "this is a writer's stage direction, not prose; rewrite each as a "
            "direct statement or question and remove the meta-commentary phrase"
        )

    # (vi) Bare prose cross-references — "see [Title], which..." without a link.
    # Detects unlinked or hallucinated references to article titles in plain
    # prose. Pattern: "see [Capitalized phrase], which" — the ", which" is a
    # strong indicator of a prose title mention rather than external attribution.
    # All BeyondTomorrow cross-references must be linked with a verified URL
    # from search_corpus, or omitted entirely.
    _bare_xref_re = _re_val.compile(
        r'\bsee\s+([A-Z][A-Za-z\s\u2019\'\-]{15,80}),\s*which\b',
        _re_val.MULTILINE,
    )
    _bare_xref_match = _bare_xref_re.search(plain_body)
    if _bare_xref_match:
        _ref_phrase = _bare_xref_match.group(1).strip()[:60]
        missing.append(
            f"prose cross-reference: 'see {_ref_phrase}...' — "
            "article titles must be linked with a verified https:// URL "
            "(from search_corpus), or omitted entirely; bare title mentions "
            "fail validation"
        )

    # --- Internal cross-reference guardrail ---
    # Scan for hyperlinks that point back to this site. For each one, verify
    # that a published post with that slug actually exists. This catches
    # hallucinated cross-references to posts that were never written.
    # If the Ghost API is unreachable we log a warning and continue — the
    # guardrail must not block publishing due to a transient network error.
    _SKIP_PREFIXES = ("tag/", "author/", "ghost/", "content/", "#", "rss/")
    _bt_domain_esc = re.escape(ghost_url or "beyondtomorrow.world")
    _internal_link_re = _re_val.compile(
        rf'href=["\']({_bt_domain_esc}/([^/"\' #]+)/)["\']',
        _re_val.IGNORECASE,
    )
    _internal_matches = _internal_link_re.findall(html_content)
    if _internal_matches:
        _published_slugs = await _fetch_published_slugs(ghost_url, admin_key)
        if _published_slugs is not None:
            for _link_url, _link_slug in _internal_matches:
                if any(_link_slug.startswith(p) for p in _SKIP_PREFIXES):
                    continue  # not a post URL
                if _link_slug not in _published_slugs:
                    missing.append(
                        f"broken internal link: '{_link_url}' references a post with "
                        f"slug '{_link_slug}' that does not exist in Ghost — "
                        "remove or correct this cross-reference before publishing"
                    )
        else:
            logger.warning(
                "Cross-reference check skipped for '%s' — Ghost API unavailable.",
                filename,
            )
    # --- End internal cross-reference guardrail ---

    if missing:
        items = '; '.join(missing)
        return (
            f"MISSING: {items} — do not publish until all items are resolved. "
            "Fix the reported issue(s) in the upstream pipeline stage and retry."
        )
    # --- End pre-publish validation ---

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
    if meta_title:
        post_payload["meta_title"] = meta_title
    if meta_description:
        post_payload["meta_description"] = meta_description
    if status == "published":
        post_payload["email_recipient_filter"] = "free"
    if feature_image_url:
        post_payload["feature_image"] = feature_image_url
        post_payload["feature_image_alt"] = image_alt

    # Derive the slug Ghost would assign (mirrors Ghost's own slugification).
    slug = re.sub(r"[^\w\s-]", "", title.lower()).strip()
    slug = re.sub(r"[\s_]+", "-", slug)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            auth_headers = {"Authorization": f"Ghost {token}", "Content-Type": "application/json"}

            # ── Delete any existing posts with this slug or numbered variants ──
            # Ghost appends -2, -3 etc. when a slug already exists. Check the
            # canonical slug plus up to 5 variants so stale duplicates are removed.
            slug_variants = [slug] + [f"{slug}-{i}" for i in range(2, 7)]
            slug_filter = ",".join(slug_variants)
            check = await client.get(
                f"{ghost_url}/ghost/api/admin/posts/?filter=slug:[{slug_filter}]&fields=id,slug&limit=20",
                headers=auth_headers,
                timeout=15.0,
            )
            if check.status_code == 200:
                for ep in check.json().get("posts", []):
                    del_resp = await client.delete(
                        f"{ghost_url}/ghost/api/admin/posts/{ep['id']}/",
                        headers=auth_headers,
                        timeout=15.0,
                    )
                    logger.info(
                        "Ghost: deleted existing post '%s' (id=%s, status=%d) before re-publish.",
                        ep.get("slug"), ep.get("id"), del_resp.status_code,
                    )

            resp = await _ghost_post_with_retry(
                client,
                f"{ghost_url}/ghost/api/admin/posts/",
                {"posts": [post_payload]},
                auth_headers,
            )
    except httpx.HTTPError as exc:
        return f"Failed to publish to Ghost: {exc}"

    post = resp.json()["posts"][0]
    return f"Published: '{post['title']}' → {post['url']} (status: {post['status']})"
