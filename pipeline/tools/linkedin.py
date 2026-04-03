"""
pipeline/tools/linkedin.py — LinkedIn cross-posting tool.

Posts a blog article card to both the personal profile and the company page
(https://www.linkedin.com/company/beyond-tomorrow-world/) immediately after Ghost publish.

Required env vars (all optional — missing vars cause graceful SKIPPED return):
    LINKEDIN_ACCESS_TOKEN  — OAuth 2.0 bearer token (expires 60 days after issue)
    LINKEDIN_PERSON_URN    — urn:li:person:{id} for the posting member
    LINKEDIN_TOKEN_EXPIRES — YYYY-MM-DD expiry date (set by scripts/linkedin_auth.py)

Optional env vars for company page posting:
    LINKEDIN_COMPANY_URN   — urn:li:organization:{id} for the company page
                             Requires w_organization_social scope in the access token.
                             Set by scripts/linkedin_auth.py or add manually.

Re-run scripts/linkedin_auth.py to refresh the token before expiry.
"""

import asyncio
import json
import logging
import os
import pathlib
import re
from datetime import date

import httpx

from pipeline._sdk import function_tool

logger = logging.getLogger(__name__)

_LINKEDIN_POSTS_URL = "https://api.linkedin.com/rest/posts"
_LINKEDIN_IMAGES_URL = "https://api.linkedin.com/rest/images?action=initializeUpload"
# Bump this when LinkedIn deprecates the current API version.
# Check https://learn.microsoft.com/en-us/linkedin/marketing/versioning
_LINKEDIN_API_VERSION = "202503"
_MAX_COMMENTARY_CHARS = 700
_RETRY_ATTEMPTS = 3
_RETRY_DELAYS = [5, 15, 30]  # seconds; conservative — LinkedIn rate limits are strict

# Path to the local dedup log — prevents reposting the same Ghost URL twice.
_POSTS_LOG = pathlib.Path(__file__).parents[2] / "logs" / "linkedin_posts.json"


def _load_posts_log() -> dict:
    """Load the LinkedIn posts dedup log from disk. Returns {} if missing or corrupt."""
    try:
        if _POSTS_LOG.is_file():
            return json.loads(_POSTS_LOG.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not read LinkedIn posts log (%s): %s", _POSTS_LOG, exc)
    return {}


def _save_posts_log(log: dict) -> None:
    """Persist the LinkedIn posts dedup log to disk."""
    try:
        _POSTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        _POSTS_LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not write LinkedIn posts log (%s): %s", _POSTS_LOG, exc)


async def _upload_image_to_linkedin(
    client: httpx.AsyncClient,
    image_url: str,
    owner_urn: str,
    access_token: str,
) -> str | None:
    """Download image from Ghost CDN and upload to LinkedIn Images API.

    owner_urn must be the URN of the author making the post (person or organization).
    Returns a LinkedIn image URN string like 'urn:li:image:...' on success,
    or None if upload fails (non-fatal — post continues without thumbnail).
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Linkedin-Version": _LINKEDIN_API_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }

    # Step 1 — initialise upload
    try:
        init_resp = await client.post(
            _LINKEDIN_IMAGES_URL,
            json={"initializeUploadRequest": {"owner": owner_urn}},
            headers=headers,
        )
    except httpx.RequestError as exc:
        logger.warning("LinkedIn image init request error: %s", exc)
        return None

    if init_resp.status_code != 200:
        logger.warning(
            "LinkedIn image init failed (%d): %s",
            init_resp.status_code,
            init_resp.text[:200],
        )
        return None

    init_data = init_resp.json().get("value", {})
    upload_url = init_data.get("uploadUrl", "")
    image_urn = init_data.get("image", "")
    if not upload_url or not image_urn:
        logger.warning("LinkedIn image init missing uploadUrl or image URN: %s", init_data)
        return None

    # Step 2 — download the image from Ghost CDN
    try:
        img_resp = await client.get(image_url, follow_redirects=True, timeout=30)
        img_resp.raise_for_status()
        image_bytes = img_resp.content
    except Exception as exc:
        logger.warning("Failed to download feature image from Ghost: %s", exc)
        return None

    # Step 3 — upload binary to LinkedIn
    try:
        up_resp = await client.put(
            upload_url,
            content=image_bytes,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=60,
        )
    except httpx.RequestError as exc:
        logger.warning("LinkedIn image upload request error: %s", exc)
        return None

    if up_resp.status_code not in (200, 201):
        logger.warning(
            "LinkedIn image upload failed (%d): %s",
            up_resp.status_code,
            up_resp.text[:200],
        )
        return None

    logger.info("Uploaded image to LinkedIn: %s", image_urn)
    return image_urn


def _build_hashtags(tags_str: str) -> str:
    """Convert a comma-separated tags string into LinkedIn hashtags.

    e.g. 'AI, Climate Change, Geopolitics' → '#AI #ClimateChange #Geopolitics'
    """
    if not tags_str:
        return ""
    tags = [t.strip() for t in tags_str.split(",") if t.strip()]
    hashtags = []
    for tag in tags[:5]:  # LinkedIn best practice: max ~5 hashtags
        # CamelCase multi-word tags, strip non-alphanumeric
        # Use w[0].upper() + w[1:] to preserve acronyms (e.g. "AI" stays "AI")
        words = re.split(r"[\s\-_]+", tag)
        camel = "".join((w[0].upper() + w[1:]) for w in words if w)
        if camel:
            hashtags.append(f"#{camel}")
    return " ".join(hashtags)


async def _post_as_author(
    client: httpx.AsyncClient,
    author_urn: str,
    label: str,
    commentary: str,
    title: str,
    post_url: str,
    description: str,
    feature_image_url: str,
    access_token: str,
    headers: dict,
) -> str:
    """POST a single LinkedIn article as the given author URN.

    Handles image upload (with author as owner), builds the payload, and runs
    the retry loop.  Returns the share URN on success (e.g. 'urn:li:share:123')
    or an 'Error: ...' string on failure — the caller decides what to do.
    """
    payload: dict = {
        "author": author_urn,
        "commentary": commentary,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "content": {
            "article": {
                "source": post_url,
                "title": title,
                "description": description,
            }
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    if feature_image_url and feature_image_url.startswith("http"):
        image_urn = await _upload_image_to_linkedin(
            client, feature_image_url, author_urn, access_token
        )
        if image_urn:
            payload["content"]["article"]["thumbnail"] = image_urn
        else:
            logger.warning(
                "LinkedIn image upload failed for %s — posting without thumbnail", label
            )

    last_error = ""
    attempts_made = 0
    for attempt in range(_RETRY_ATTEMPTS):
        attempts_made = attempt + 1
        if attempt > 0:
            delay = _RETRY_DELAYS[attempt - 1]
            logger.info(
                "LinkedIn (%s): waiting %ds before retry (attempt %d/%d)",
                label, delay, attempts_made, _RETRY_ATTEMPTS,
            )
            await asyncio.sleep(delay)

        try:
            resp = await client.post(_LINKEDIN_POSTS_URL, json=payload, headers=headers)
        except httpx.RequestError as exc:
            last_error = f"Network error: {exc}"
            logger.warning(
                "LinkedIn %s request error (attempt %d): %s", label, attempts_made, exc
            )
            continue

        if resp.status_code == 201:
            post_id = resp.headers.get("x-restli-id", resp.headers.get("X-RestLi-Id", ""))
            # x-restli-id already contains the full URN (e.g. urn:li:share:...)
            # Only prepend the prefix if it's a bare numeric ID.
            linkedin_urn = (
                post_id if post_id.startswith("urn:li:")
                else f"urn:li:share:{post_id}"
            )
            logger.info("Published to LinkedIn (%s): %s", label, linkedin_urn)
            return linkedin_urn

        if resp.status_code == 429:
            last_error = "Rate limited (429)"
            logger.warning(
                "LinkedIn %s rate limited (attempt %d/%d)", label, attempts_made, _RETRY_ATTEMPTS
            )
            continue

        if resp.status_code == 401:
            return (
                f"Error: LinkedIn token is invalid or expired (401) for {label}. "
                "Re-run scripts/linkedin_auth.py to refresh LINKEDIN_ACCESS_TOKEN."
            )

        if resp.status_code == 403:
            return (
                f"Error: LinkedIn permission denied (403) for {label}. "
                f"Ensure 'Share on LinkedIn' / 'w_organization_social' product is approved "
                f"in the developer portal. Response: {resp.text[:300]}"
            )

        # Any other non-2xx — non-retriable
        last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
        logger.error(
            "LinkedIn %s API error (attempt %d): %s", label, attempts_made, last_error
        )
        break

    return (
        f"Error: LinkedIn {label} post failed after {attempts_made} attempt(s). "
        f"Last error: {last_error}"
    )


@function_tool
async def post_to_linkedin(
    title: str,
    excerpt: str,
    post_url: str,
    tags: str = "",
    feature_image_url: str = "",
) -> str:
    """Post a blog article card to the LinkedIn personal profile and company page.

    Posts as the authenticated member (LINKEDIN_PERSON_URN) and, if
    LINKEDIN_COMPANY_URN is set, also as the Beyond Tomorrow company page.
    Each destination is posted independently — a failure on one does not block
    the other.

    Args:
        title:             Blog post title (used as the article card title).
        excerpt:           One-to-two sentence summary (used as commentary and card description).
        post_url:          Canonical Ghost URL of the published post.
        tags:              Comma-separated post tags, converted to hashtags (optional).
        feature_image_url: Ghost CDN URL of the feature image (optional). Uploaded
                           separately for each destination so thumbnails are always correct.

    Returns:
        'Personal: urn:li:share:{id} | Company: urn:li:share:{id}'  both succeeded
        'Personal: urn:li:share:{id}'                                personal only
        'SKIPPED: LinkedIn not configured'                           env vars missing
        'Error: {details}'                                           API failure
    """
    access_token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()
    person_urn = os.environ.get("LINKEDIN_PERSON_URN", "").strip()

    if not access_token or not person_urn:
        logger.info("LinkedIn not configured — skipping cross-post.")
        return "SKIPPED: LinkedIn not configured"

    # Validate personal URN format
    if not person_urn.startswith("urn:li:person:"):
        return (
            f"Error: LINKEDIN_PERSON_URN has invalid format: {person_urn!r}. "
            "Expected urn:li:person:{id}"
        )

    # Optional company page URN
    company_urn = os.environ.get("LINKEDIN_COMPANY_URN", "").strip()
    if company_urn and not company_urn.startswith("urn:li:organization:"):
        logger.warning(
            "LINKEDIN_COMPANY_URN has unexpected format %r — skipping company post. "
            "Expected urn:li:organization:{id}.",
            company_urn,
        )
        company_urn = ""

    # Warn if token is close to expiry (non-blocking)
    token_expires = os.environ.get("LINKEDIN_TOKEN_EXPIRES", "").strip()
    if token_expires:
        try:
            days_left = (date.fromisoformat(token_expires) - date.today()).days
            if days_left <= 0:
                logger.warning(
                    "LinkedIn access token EXPIRED on %s — post may fail. "
                    "Re-run scripts/linkedin_auth.py to refresh.",
                    token_expires,
                )
            elif days_left <= 7:
                logger.warning(
                    "LinkedIn access token expires in %d day(s) on %s. "
                    "Re-run scripts/linkedin_auth.py soon.",
                    days_left,
                    token_expires,
                )
        except ValueError:
            logger.warning("LINKEDIN_TOKEN_EXPIRES has invalid date format: %r", token_expires)

    # Build shared commentary (same text for both personal and company posts)
    excerpt_clean = excerpt.strip()
    hashtags = _build_hashtags(tags)
    commentary = excerpt_clean
    if hashtags:
        max_excerpt = _MAX_COMMENTARY_CHARS - len(hashtags) - 2
        if len(commentary) > max_excerpt:
            commentary = commentary[:max_excerpt].rsplit(" ", 1)[0].rstrip(".,;:") + "..."
        commentary = f"{commentary}\n\n{hashtags}"
    else:
        if len(commentary) > _MAX_COMMENTARY_CHARS:
            commentary = commentary[:_MAX_COMMENTARY_CHARS].rsplit(" ", 1)[0].rstrip(".,;:") + "..."

    description = excerpt_clean[:200]

    posts_log = _load_posts_log()

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Linkedin-Version": _LINKEDIN_API_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }

    results: list[str] = []

    async with httpx.AsyncClient(timeout=30) as client:

        # ── Personal post ──────────────────────────────────────────────────
        personal_log_key = post_url
        if personal_log_key in posts_log:
            existing = posts_log[personal_log_key]
            logger.info("LinkedIn personal: already posted as %s — skipping.", existing)
            results.append(f"Personal: SKIPPED (already posted as {existing})")
        else:
            personal_result = await _post_as_author(
                client, person_urn, "personal",
                commentary, title, post_url, description,
                feature_image_url, access_token, headers,
            )
            if personal_result.startswith("urn:li:share:"):
                posts_log[personal_log_key] = personal_result
                _save_posts_log(posts_log)
                results.append(f"Personal: {personal_result}")
            else:
                results.append(f"Personal: {personal_result}")

        # ── Company post (optional) ────────────────────────────────────────
        if company_urn:
            company_log_key = f"{post_url}|{company_urn}"
            if company_log_key in posts_log:
                existing = posts_log[company_log_key]
                logger.info("LinkedIn company: already posted as %s — skipping.", existing)
                results.append(f"Company: SKIPPED (already posted as {existing})")
            else:
                company_result = await _post_as_author(
                    client, company_urn, "company",
                    commentary, title, post_url, description,
                    feature_image_url, access_token, headers,
                )
                if company_result.startswith("urn:li:share:"):
                    posts_log[company_log_key] = company_result
                    _save_posts_log(posts_log)
                    results.append(f"Company: {company_result}")
                else:
                    results.append(f"Company: {company_result}")

    return " | ".join(results)
