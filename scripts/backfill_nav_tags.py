"""Backfill nav tags on recent Ghost posts using the same normaliser the
pipeline now applies at publish time.

Usage:
    python scripts/backfill_nav_tags.py            # dry-run (no writes)
    python scripts/backfill_nav_tags.py --apply    # apply updates to Ghost
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.tools.tags import normalise_tags  # noqa: E402

load_dotenv()

LIMIT = 30
APPLY = "--apply" in sys.argv

GHOST_URL = os.environ["GHOST_URL"].rstrip("/")
KEY = os.environ["GHOST_ADMIN_KEY"]
KID, SECRET = KEY.split(":", 1)


def token() -> str:
    now = int(time.time())
    h = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "kid": KID, "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(
        json.dumps({"iat": now, "exp": now + 300, "aud": "/admin/"}).encode()
    ).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(
        hmac.new(bytes.fromhex(SECRET), f"{h}.{p}".encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{h}.{p}.{sig}"


def main() -> None:
    with httpx.Client(timeout=30.0) as client:
        r = client.get(
            f"{GHOST_URL}/ghost/api/admin/posts/"
            f"?limit={LIMIT}&order=published_at%20desc&include=tags"
            f"&fields=id,title,slug,updated_at",
            headers={"Authorization": f"Ghost {token()}"},
        )
        r.raise_for_status()
        posts = r.json()["posts"]

        changed = 0
        for post in posts:
            current = [t["name"] for t in post.get("tags", [])]
            current_str = ", ".join(current)
            new_str = normalise_tags(current_str)
            new_tags = [t.strip() for t in new_str.split(",") if t.strip()]
            if new_tags == current:
                continue

            added = [t for t in new_tags if t not in current]
            changed += 1
            print(f"\n{post['slug']}")
            print(f"  before: {current}")
            print(f"  after : {new_tags}   (+{added})")

            if APPLY:
                upd = client.put(
                    f"{GHOST_URL}/ghost/api/admin/posts/{post['id']}/",
                    headers={
                        "Authorization": f"Ghost {token()}",
                        "Content-Type": "application/json",
                    },
                    json={"posts": [{
                        "updated_at": post["updated_at"],
                        "tags": [{"name": t} for t in new_tags],
                    }]},
                )
                upd.raise_for_status()
                print("  -> updated in Ghost")

        print(f"\n{'APPLIED' if APPLY else 'DRY-RUN'}: {changed} post(s) "
              f"{'updated' if APPLY else 'would change'}.")


if __name__ == "__main__":
    main()
