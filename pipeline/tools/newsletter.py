"""
pipeline/tools/newsletter.py — Resend newsletter sender for BeyondTomorrow.World

Sends a per-member newsletter email via Resend immediately after each Ghost publish.
Bypasses Ghost's Mailgun requirement entirely.

Called by pipeline/main.py after Step 4 (Publish) and Step 4b (LinkedIn).
"""

from __future__ import annotations

import asyncio
import html as _html
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import quote as _url_quote
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import jwt

logger = logging.getLogger("pipeline")


_EMAIL_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background-color:#f5f5f0;font-family:Georgia,serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f5f0;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

        <!-- Header -->
        <tr>
          <td style="background-color:#0d1b2a;padding:24px 32px;border-radius:8px 8px 0 0;">
            <a href="{site_url}" style="text-decoration:none;">
              <span style="color:#e8d5b7;font-size:22px;font-weight:bold;letter-spacing:1px;">
                Beyond Tomorrow
              </span>
            </a>
          </td>
        </tr>

        <!-- Feature image -->
        {feature_image_block}

        <!-- Body -->
        <tr>
          <td style="background-color:#ffffff;padding:36px 32px;">
            <h1 style="margin:0 0 16px;font-size:26px;line-height:1.3;color:#0d1b2a;">
              {title}
            </h1>
            <p style="margin:0 0 28px;font-size:16px;line-height:1.7;color:#444444;">
              {excerpt}
            </p>
            <a href="{post_url}"
               style="display:inline-block;background-color:#0d1b2a;color:#e8d5b7;
                      text-decoration:none;padding:14px 28px;border-radius:4px;
                      font-size:15px;font-weight:bold;">
              Read the full post &rarr;
            </a>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background-color:#f5f5f0;padding:20px 32px;border-radius:0 0 8px 8px;">
            <p style="margin:0;font-size:12px;color:#888888;text-align:center;">
              You're receiving this because you subscribed to Beyond Tomorrow.<br>
              <a href="{unsubscribe_url}" style="color:#888888;">Unsubscribe</a>
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>
"""

_FEATURE_IMAGE_BLOCK = """\
<tr>
  <td style="background-color:#ffffff;padding:0;">
    <img src="{src}" alt="" width="600"
         style="display:block;width:100%;max-width:600px;height:auto;" />
  </td>
</tr>
"""

# Legacy sent URLs are read only during transition; all new receipts are in PostgreSQL.
_SENT_LOG = Path(__file__).resolve().parent.parent.parent / "logs" / "newsletter_sent.json"


def _load_sent_urls() -> set:
    try:
        return set(json.loads(_SENT_LOG.read_text()))
    except (OSError, ValueError):
        return set()


def _eligible_member(member: dict, newsletter_id: str) -> bool:
    if member.get('status') != 'free' or member.get('subscribed') is False or member.get('subscribed_to_emails') is False:
        return False
    if (member.get('email_suppression') or {}).get('suppressed'):
        return False
    return any(n.get('id') == newsletter_id for n in member.get('newsletters', []))


def _unsubscribe_url(member, newsletter, site):
    native = member.get('unsubscribe_url')
    if native:
        parts = urlsplit(native)
        origin = urlsplit(site)
        if (parts.scheme, parts.netloc) != (origin.scheme, origin.netloc):
            raise ValueError('Ghost returned an unsubscribe URL outside the configured site')
        query = dict(parse_qsl(parts.query))
        query['newsletter'] = newsletter['uuid']
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
    return (f"{site}/unsubscribe/?uuid={_url_quote(member['uuid'], safe='')}"
            f"&newsletter={_url_quote(newsletter['uuid'], safe='')}")


async def _send_member(client, headers, article, recipient, payload):
    from pipeline.storage.deliveries import delivery_record, private_key
    async with delivery_record('newsletter', article, private_key(recipient.lower())) as receipt:
        if receipt.status == 'sent':
            return 'already_sent'
        if receipt.status == 'sending':
            if time.time() - receipt.data.get('started_at', 0) > 23 * 3600:
                raise RuntimeError('Uncertain newsletter delivery requires reconciliation after idempotency expiry')
            payload = receipt.data['payload']
        else:
            await receipt.save('sending', data={'payload': payload, 'started_at': time.time()})
        request_headers = {**headers, 'Idempotency-Key': 'newsletter/' + private_key(article + '/' + recipient.lower())}
        for attempt in range(2):
            try:
                response = await client.post('https://api.resend.com/emails', json=payload, headers=request_headers)
            except httpx.RequestError:
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                raise RuntimeError('Newsletter response uncertain; receipt retained for safe retry') from None
            if response.status_code in (200, 201):
                await receipt.save('sent', response.json().get('id'), data={})
                return 'sent'
            if response.status_code >= 500 or response.status_code in (408, 429):
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                raise RuntimeError('Newsletter provider unavailable; receipt retained for safe retry')
            # A definitive validation/auth rejection did not deliver the email.
            await receipt.save('failed', data={})
            raise RuntimeError(f'Newsletter provider rejected request (HTTP {response.status_code})')


def _ghost_token() -> str:
    admin_key = os.environ["GHOST_ADMIN_KEY"]
    key_id, secret = admin_key.split(":", 1)
    iat = int(time.time())
    return jwt.encode(
        {"iat": iat, "exp": iat + 300, "aud": "/admin/"},
        bytes.fromhex(secret),
        algorithm="HS256",
        headers={"alg": "HS256", "typ": "JWT", "kid": key_id},
    )


async def send_newsletter(
    post_url: str,
    title: str,
    excerpt: str,
    feature_image_url: str = "",
) -> str:
    """Send a newsletter email to all free Ghost members via Resend.

    Returns a summary string like:
        "Newsletter sent to 2 member(s) via Resend"
    or an error string starting with "Error:".
    """
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not resend_key:
        return "SKIPPED: RESEND_API_KEY not set"

    ghost_url = os.environ.get("GHOST_URL", "").rstrip("/")
    if not ghost_url:
        return "Error: GHOST_URL not set"

    # Deduplication: skip if this post URL was already successfully emailed.
    if post_url in _load_sent_urls():
        logger.info("Newsletter: already sent for %s — skipping", post_url)
        return f"SKIPPED: already sent newsletter for {post_url}"

    resend_headers = {
        "Authorization": f"Bearer {resend_key}",
        "Content-Type": "application/json",
    }
    ghost_headers = lambda: {
        "Authorization": f"Ghost {_ghost_token()}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        # ── Fetch live post excerpt from Ghost Admin API ──────────────────────
        # Use the published post's custom_excerpt so the newsletter always
        # mirrors what Ghost shows on the post card.
        try:
            slug = post_url.rstrip("/").rsplit("/", 1)[-1]
            post_resp = await client.get(
                f"{ghost_url}/ghost/api/admin/posts/slug/{slug}/",
                params={"fields": "custom_excerpt,title"},
                headers=ghost_headers(),
            )
            if post_resp.status_code == 200:
                post_data = post_resp.json().get("posts", [{}])[0]
                live_excerpt = (post_data.get("custom_excerpt") or "").strip()
                live_title = (post_data.get("title") or "").strip()
                if live_excerpt:
                    excerpt = live_excerpt
                if live_title:
                    title = live_title
        except Exception as _exc:
            logger.warning("Newsletter: could not fetch live post data — %s; using frontmatter values", _exc)

        newsletters_response = await client.get(f"{ghost_url}/ghost/api/admin/newsletters/?limit=100", headers=ghost_headers())
        newsletters_response.raise_for_status()
        newsletters = [n for n in newsletters_response.json().get('newsletters', []) if n.get('status') == 'active']
        requested_id = os.environ.get('GHOST_NEWSLETTER_ID', '').strip()
        if requested_id:
            newsletters = [n for n in newsletters if n.get('id') == requested_id]
        if len(newsletters) != 1 or not newsletters[0].get('uuid'):
            return 'Error: select one active newsletter with GHOST_NEWSLETTER_ID before sending'
        newsletter = newsletters[0]

        # ── Fetch all free members from Ghost Admin API ───────────────────────
        try:
            members: list[dict] = []
            page = 1
            while True:
                # Build URL manually — httpx percent-encodes ':' in params which
                # breaks Ghost's NQL filter syntax (status:free → status%3Afree).
                # Do not restrict fields — unsubscribe_url is not a filterable field
                # name and causes a 400 if passed in &fields=.
                members_url = (
                    f"{ghost_url}/ghost/api/admin/members/"
                    f"?filter=status:free&include=newsletters&limit=100&page={page}"
                )
                r = await client.get(members_url, headers=ghost_headers())
                r.raise_for_status()
                data = r.json()
                batch = data.get("members", [])
                members.extend(m for m in batch if _eligible_member(m, newsletter['id']))
                # Ghost pagination — stop when fewer than 100 returned
                if len(batch) < 100:
                    break
                page += 1
        except Exception as exc:
            return f"Error: fetching Ghost members failed — {exc}"

        if not members:
            return "SKIPPED: no subscribed free members found"

        logger.info("Newsletter: sending to %d member(s)", len(members))

        # ── Build HTML email ──────────────────────────────────────────────────
        feature_block = (
            _FEATURE_IMAGE_BLOCK.format(src=_html.escape(feature_image_url, quote=True))
            if feature_image_url
            else ""
        )

        # Escape user-controlled content for safe HTML insertion.
        # Also neutralise Python .format() injection by replacing bare braces.
        def _safe(text: str) -> str:
            return _html.escape(text.replace("{", "&#123;").replace("}", "&#125;"))

        safe_title = _safe(title)
        safe_excerpt = _safe(excerpt)

        sent = 0
        errors: list[str] = []
        already_sent = 0

        for member in members:
            email_addr = member.get("email", "")
            if not email_addr:
                continue
            name = member.get("name") or ""
            if not member.get('uuid'):
                errors.append('Member lacks unsubscribe identifier')
                continue
            unsubscribe_url = _unsubscribe_url(member, newsletter, ghost_url)

            html = _EMAIL_TEMPLATE.format(
                title=safe_title,
                excerpt=safe_excerpt,
                post_url=_html.escape(post_url, quote=True),
                site_url=_html.escape(ghost_url, quote=True),
                unsubscribe_url=_html.escape(unsubscribe_url, quote=True),
                feature_image_block=feature_block,
            )

            payload = {
                "from": "Beyond Tomorrow <admin@beyondtomorrow.world>",
                "to": [f"{name} <{email_addr}>" if name else email_addr],
                "subject": title,
                "html": html,
            }

            try:
                outcome = await _send_member(client, resend_headers, post_url, email_addr, payload)
                if outcome == 'already_sent':
                    already_sent += 1
                else:
                    sent += 1
            except Exception as exc:
                errors.append(type(exc).__name__)
                logger.warning('Newsletter recipient delivery incomplete (%s)', type(exc).__name__)
            await asyncio.sleep(0.1)

    if errors:
        return f"Error: newsletter incomplete: {sent} sent, {already_sent} previously sent, {len(errors)} failed; retry only unfinished deliveries"
    if already_sent == len(members):
        return 'SKIPPED: newsletter already delivered to all subscribed members'
    return f"Newsletter sent to {sent} member(s) via Resend; {already_sent} previously delivered"
