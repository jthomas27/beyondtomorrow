"""scripts/delete_ghost_post.py

Delete a Ghost post (and all its numbered slug variants) by title slug.

Useful when cleaning up duplicate posts created by re-publish runs before
the auto-delete guardrail was in place (-2, -3 suffixes, etc.).

Usage:
    .venv/bin/python scripts/delete_ghost_post.py <slug-or-url>

    <slug-or-url> can be:
      - a Ghost slug:   ai-agents-under-fire-cybersecurity-risks-for-business-and-consumers
      - a Ghost URL:    https://beyondtomorrow.world/ai-agents-under-fire.../

Examples:
    .venv/bin/python scripts/delete_ghost_post.py ai-agents-under-fire-cybersecurity-risks-for-business-and-consumers
    .venv/bin/python scripts/delete_ghost_post.py https://beyondtomorrow.world/my-post-slug/

Requires GHOST_URL and GHOST_ADMIN_KEY in .env.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from dotenv import load_dotenv
load_dotenv()

import httpx
import jwt


def _ghost_token() -> str:
    key = os.environ["GHOST_ADMIN_KEY"]
    kid, secret = key.split(":")
    iat = int(time.time())
    payload = {"iat": iat, "exp": iat + 300, "aud": "/admin/"}
    return jwt.encode(payload, bytes.fromhex(secret), algorithm="HS256", headers={"kid": kid})


def _extract_slug(arg: str) -> str:
    """Return a bare slug from either a URL or a plain slug string."""
    arg = arg.rstrip("/")
    if arg.startswith("http"):
        return arg.split("/")[-1]
    return arg


async def delete_slug_variants(slug: str) -> None:
    base = os.environ.get("GHOST_URL", "").rstrip("/")
    if not base:
        print("Error: GHOST_URL not set in environment.")
        sys.exit(1)

    token = _ghost_token()
    headers = {"Authorization": f"Ghost {token}"}

    variants = [slug] + [f"{slug}-{i}" for i in range(2, 7)]
    slug_filter = ",".join(variants)

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"{base}/ghost/api/admin/posts/?filter=slug:[{slug_filter}]&fields=id,slug,title,status&limit=20",
            headers=headers,
        )
        if r.status_code != 200:
            print(f"Error querying Ghost: {r.status_code} {r.text[:200]}")
            sys.exit(1)

        posts = r.json().get("posts", [])
        if not posts:
            print(f"No posts found matching slug variants of: {slug!r}")
            return

        print(f"Found {len(posts)} post(s):")
        for p in posts:
            print(f"  {p['slug']!r}  (id={p['id']}, status={p['status']}, title={p['title']!r})")

        confirm = input("\nDelete all of the above? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

        for p in posts:
            dr = await client.delete(
                f"{base}/ghost/api/admin/posts/{p['id']}/",
                headers=headers,
            )
            status = "OK" if dr.status_code in (200, 204) else f"ERROR {dr.status_code}"
            print(f"  {status}  deleted {p['slug']!r} (id={p['id']})")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    slug = _extract_slug(sys.argv[1])
    print(f"Looking for Ghost posts with slug base: {slug!r}\n")
    asyncio.run(delete_slug_variants(slug))


if __name__ == "__main__":
    main()
