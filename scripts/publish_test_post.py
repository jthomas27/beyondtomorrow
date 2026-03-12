"""Direct Ghost publish test — calls Ghost Admin API directly to verify publishing."""
import os
import sys
import time
import json
import base64
import hashlib
import hmac
import asyncio
import sys
sys.path.insert(0, "/Users/jeremiah/Projects/BeyondTomorrow.World")

import httpx

# Load .env
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

if not GHOST_URL or not ADMIN_KEY or ":" not in ADMIN_KEY:
    print("ERROR: GHOST_URL or GHOST_ADMIN_KEY not set correctly.")
    sys.exit(1)

key_id, secret_hex = ADMIN_KEY.split(":", 1)

# Build JWT
now = int(time.time())
header_b = base64.urlsafe_b64encode(
    json.dumps({"alg": "HS256", "kid": key_id, "typ": "JWT"}).encode()
).rstrip(b"=").decode()
payload_b = base64.urlsafe_b64encode(
    json.dumps({"iat": now, "exp": now + 300, "aud": "/admin/"}).encode()
).rstrip(b"=").decode()
sig = base64.urlsafe_b64encode(
    hmac.new(
        bytes.fromhex(secret_hex),
        f"{header_b}.{payload_b}".encode(),
        digestmod=hashlib.sha256,
    ).digest()
).rstrip(b"=").decode()
token = f"{header_b}.{payload_b}.{sig}"

HTML = """<p><strong>⚠️ TEST POST — Please ignore or delete after review.</strong></p>

<p>We interrupt your regularly scheduled apocalypse to bring you this important announcement: AI is here, it's (mostly) harmless, and it just tried to fold a napkin into a swan. Results were mixed.</p>

<p>Every week, a new model drops that is "the most capable ever created" — surpassing human reasoning, acing bar exams, writing poetry that made a tech blogger cry (the blogger insists it was allergies). Meanwhile, your smart speaker still mishears "set a timer" as "call your mother."</p>

<h2>A Joke About AI</h2>

<p>Why did the AI break up with its dataset?</p>
<p><em>Too many missing values.</em></p>

<h2>What to Expect from This Blog</h2>

<p>BeyondTomorrow.World is an automated research-to-publish pipeline. This post was generated to verify the plumbing works. Future posts will cover real AI developments, with sources, analysis, and the occasional existential aside.</p>

<p>If you can read this, the robots are working. Mostly.</p>

<p><em>— The BeyondTomorrow.World Research Agent (a.k.a. a bunch of Python and some API keys)</em></p>"""

post_data = {
    "posts": [{
        "title": "We Taught a Machine to Think. It Immediately Asked for a Coffee Break.",
        "html": HTML,
        "tags": [{"name": "AI"}, {"name": "test"}, {"name": "humor"}],
        "custom_excerpt": "A short humorous test post verifying the automated publishing pipeline. Contains one (1) AI joke.",
        "status": "draft",
    }]
}

async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{GHOST_URL}/ghost/api/admin/posts/?source=html",
            json=post_data,
            headers={
                "Authorization": f"Ghost {token}",
                "Content-Type": "application/json",
                "Accept-Version": "v5.0",
            },
        )
        if resp.status_code >= 400:
            print(f"HTTP {resp.status_code}: {resp.text[:500]}")
            sys.exit(1)
        post = resp.json()["posts"][0]
        print(f"Published (draft): '{post['title']}'")
        print(f"  Status: {post['status']}")
        print(f"  URL: {post['url']}")
        print(f"  Admin preview: {GHOST_URL}/ghost/#/editor/post/{post['id']}")

asyncio.run(main())
