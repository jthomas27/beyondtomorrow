"""Check Ghost CMS for recent posts/drafts and list research/ directory."""
import urllib.request
import json
import base64
import hashlib
import time
import hmac as _hmac
import os

# Check research directory
research_dir = "/Users/jeremiah/Projects/BeyondTomorrow.World/research"
if os.path.exists(research_dir):
    files = os.listdir(research_dir)
    print(f"research/ directory: {len(files)} files")
    for f in sorted(files):
        print(f"  {f}")
else:
    print("research/ directory: empty or not found")

print()

# Check Ghost for recent posts
key = os.environ["GHOST_ADMIN_KEY"]
kid, secret = key.split(":", 1)
now = int(time.time())
header = base64.urlsafe_b64encode(
    json.dumps({"alg": "HS256", "kid": kid, "typ": "JWT"}).encode()
).rstrip(b"=").decode()
payload = base64.urlsafe_b64encode(
    json.dumps({"iat": now, "exp": now + 300, "aud": "/admin/"}).encode()
).rstrip(b"=").decode()
sig_input = f"{header}.{payload}".encode()
sig = base64.urlsafe_b64encode(
    _hmac.new(bytes.fromhex(secret), sig_input, digestmod=hashlib.sha256).digest()
).rstrip(b"=").decode()
token = f"{header}.{payload}.{sig}"

req = urllib.request.Request(
    "https://beyondtomorrow.world/ghost/api/admin/posts/?limit=10&order=created_at%20desc&fields=title,status,url,created_at",
    headers={"Authorization": f"Ghost {token}", "Accept": "application/json"},
)
data = json.loads(urllib.request.urlopen(req).read())
posts = data.get("posts", [])
print(f"Ghost posts (most recent {len(posts)}):")
for p in posts:
    print(f"  [{p.get('status','?')}] {p.get('title','?')[:70]}")
    print(f"         {p.get('url','?')}")
