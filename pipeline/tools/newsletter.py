"""
pipeline/tools/newsletter.py — Resend newsletter sender for BeyondTomorrow.World

Sends a per-member newsletter email via Resend immediately after each Ghost publish.
Bypasses Ghost's Mailgun requirement entirely.

Called by pipeline/main.py after Step 4 (Publish) and Step 4b (LinkedIn).
"""

from __future__ import annotations

import logging
import os
import time

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

    resend_headers = {
        "Authorization": f"Bearer {resend_key}",
        "Content-Type": "application/json",
    }
    ghost_headers = lambda: {
        "Authorization": f"Ghost {_ghost_token()}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
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
                    f"?filter=status:free&limit=100&page={page}"
                )
                r = await client.get(members_url, headers=ghost_headers())
                r.raise_for_status()
                data = r.json()
                batch = data.get("members", [])
                members.extend(batch)
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
            _FEATURE_IMAGE_BLOCK.format(src=feature_image_url)
            if feature_image_url
            else ""
        )

        sent = 0
        errors: list[str] = []

        for member in members:
            email_addr = member.get("email", "")
            if not email_addr:
                continue
            name = member.get("name") or ""
            unsubscribe_url = (
                member.get("unsubscribe_url")
                or f"{ghost_url}/unsubscribe/?email={email_addr}"
            )

            html = _EMAIL_TEMPLATE.format(
                title=title,
                excerpt=excerpt,
                post_url=post_url,
                site_url=ghost_url,
                unsubscribe_url=unsubscribe_url,
                feature_image_block=feature_block,
            )

            payload = {
                "from": "Beyond Tomorrow <admin@beyondtomorrow.world>",
                "to": [f"{name} <{email_addr}>" if name else email_addr],
                "subject": title,
                "html": html,
            }

            try:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    json=payload,
                    headers=resend_headers,
                )
                if resp.status_code == 200:
                    sent += 1
                    logger.info("Newsletter: sent to %s (id=%s)", email_addr, resp.json().get("id"))
                else:
                    err = f"{email_addr}: {resp.status_code} {resp.text[:100]}"
                    errors.append(err)
                    logger.warning("Newsletter: failed for %s", err)
            except Exception as exc:
                errors.append(f"{email_addr}: {exc}")
                logger.warning("Newsletter: exception for %s: %s", email_addr, exc)

    if errors and sent == 0:
        return f"Error: all {len(errors)} sends failed — {errors[0]}"
    if errors:
        return f"Newsletter sent to {sent}/{len(members)} member(s) via Resend; {len(errors)} failed: {errors[0]}"
    return f"Newsletter sent to {sent} member(s) via Resend"
