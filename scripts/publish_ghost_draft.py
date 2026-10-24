"""Publish the draft test post on Ghost CMS."""
import os
import sys
import time
import json
import base64
import hashlib
import hmac
import asyncio
sys.path.insert(0, "/Users/jeremiah/Projects/BeyondTomorrow.World")
import httpx

env_path = "/Users/jeremiah/Projects/BeyondTomorrow.World/.env"
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v

GHOST_URL = os.environ.get("GHOST_URL", "").rstrip("/")
ADMIN_KEY = os.environ.get("GHOST_ADMIN_KEY", "")
key_id, secret_hex = ADMIN_KEY.split(":", 1)

def make_token():
    now = int(time.time())
    h = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "kid": key_id, "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(
        json.dumps({"iat": now, "exp": now + 300, "aud": "/admin/"}).encode()
    ).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(
        hmac.new(bytes.fromhex(secret_hex), f"{h}.{p}".encode(), digestmod=hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{h}.{p}.{sig}"

async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Find the draft by title
        resp = await client.get(
            f"{GHOST_URL}/ghost/api/admin/posts/?filter=status:draft&limit=5&fields=id,title,status,updated_at",
            headers={"Authorization": f"Ghost {make_token()}", "Accept-Version": "v5.0"},
        )
        resp.raise_for_status()
        posts = resp.json().get("posts", [])
        print(f"Found {len(posts)} draft(s):")
        for p in posts:
            print(f"  [{p['id']}] {p['title'][:70]}")

        target = next(
            (p for p in posts if "Coffee Break" in p["title"] or "Machine to Think" in p["title"]),
            None,
        )
        if not target:
            print("\nTarget draft not found. Showing all drafts above — set post_id manually.")
            sys.exit(1)

        post_id = target["id"]
        updated_at = target["updated_at"]
        print(f"\nPublishing post: {target['title']}")

        # Update status to published
        resp2 = await client.put(
            f"{GHOST_URL}/ghost/api/admin/posts/{post_id}/?source=html",
            json={"posts": [{"status": "published", "updated_at": updated_at}]},
            headers={
                "Authorization": f"Ghost {make_token()}",
                "Content-Type": "application/json",
                "Accept-Version": "v5.0",
            },
        )
        if resp2.status_code >= 400:
            print(f"Error {resp2.status_code}: {resp2.text[:400]}")
            sys.exit(1)
        post = resp2.json()["posts"][0]
        print(f"\nPublished: '{post['title']}'")
        print(f"  Status: {post['status']}")
        print(f"  URL: {post['url']}")

asyncio.run(main())
