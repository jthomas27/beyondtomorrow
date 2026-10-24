"""
Test the Resend newsletter sender end-to-end.

Steps:
  1. Publish a minimal test post to Ghost (status=published)
  2. Call send_newsletter() — fetches Ghost members, sends via Resend
  3. Delete the test post from Ghost
  4. Report results

Usage:
  .venv/bin/python scripts/test_email_notify.py
"""

import asyncio
import os
import time

import httpx
import jwt
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

# Must be on path before importing pipeline
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from pipeline.tools.newsletter import send_newsletter


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


LEXICAL = (
    '{"root":{"children":[{"type":"html","html":"<p>This is an automated test post '
    "from the BeyondTomorrow pipeline. If you received an email notification for this "
    'post, the Resend newsletter integration is working correctly.</p>"}],'
    '"direction":null,"format":"","indent":0,"type":"root","version":1}}'
)

TEST_TITLE   = "[TEST] Email notification check — please ignore"
TEST_EXCERPT = "Automated pipeline test. You received this because the newsletter sender is working."
TEST_IMAGE   = "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=600&q=80"


async def main() -> None:
    ghost_url = os.environ["GHOST_URL"].rstrip("/")
    base = f"{ghost_url}/ghost/api/admin"
    headers = lambda: {
        "Authorization": f"Ghost {_ghost_token()}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        # ── 1. Publish test post ──────────────────────────────────────────────
        payload = {
            "posts": [{
                "title": TEST_TITLE,
                "lexical": LEXICAL,
                "status": "published",
                "tags": [{"name": "test"}],
                "custom_excerpt": TEST_EXCERPT,
                "feature_image": TEST_IMAGE,
            }]
        }
        print("Publishing test post to Ghost…")
        resp = await client.post(f"{base}/posts/", json=payload, headers=headers())
        resp.raise_for_status()
        post = resp.json()["posts"][0]
        post_id  = post["id"]
        post_url = post["url"]
        print(f"  URL:    {post_url}")
        print(f"  Status: {post['status']}")

        # ── 2. Send newsletter via Resend ────────────────────────────────────
        print("\nSending newsletter via Resend…")
        result = await send_newsletter(
            post_url=post_url,
            title=TEST_TITLE,
            excerpt=TEST_EXCERPT,
            feature_image_url=TEST_IMAGE,
        )
        print(f"  Result: {result}")

        # ── 3. Delete test post ───────────────────────────────────────────────
        print("\nDeleting test post from Ghost…")
        del_resp = await client.delete(f"{base}/posts/{post_id}/", headers=headers())
        if del_resp.status_code in (200, 204):
            print(f"  Deleted (id={post_id})")
        else:
            print(f"  Warning: delete returned {del_resp.status_code} — remove manually in Ghost Admin")

    print("\n─────────────────────────────────────────")
    if result.startswith("Error:"):
        print(f"FAILED: {result}")
    elif result.startswith("SKIPPED:"):
        print(f"SKIPPED: {result}")
        print("Set RESEND_API_KEY in .env to enable newsletters.")
    else:
        print(f"SUCCESS: {result}")
        print("\nCheck these inboxes for the newsletter email:")
        print("  • jeremiah.thomas2701@gmail.com")
        print("  • admin@beyondtomorrow.world")


if __name__ == "__main__":
    asyncio.run(main())
