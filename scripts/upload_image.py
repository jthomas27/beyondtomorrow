"""Upload a local image to Ghost CMS and print the hosted URL."""
import os, time, sys
import jwt
import httpx
from dotenv import load_dotenv

load_dotenv()

ghost_url = os.environ.get("GHOST_URL", "").rstrip("/")
admin_key = os.environ.get("GHOST_ADMIN_KEY", "")

if not ghost_url or not admin_key:
    print("Error: GHOST_URL and GHOST_ADMIN_KEY must be set in .env")
    sys.exit(1)

key_id, secret = admin_key.split(":", 1)
iat = int(time.time())
header = {"alg": "HS256", "typ": "JWT", "kid": key_id}
payload = {"iat": iat, "exp": iat + 300, "aud": "/admin/"}
token = jwt.encode(payload, bytes.fromhex(secret), algorithm="HS256", headers=header)

image_path = sys.argv[1] if len(sys.argv) > 1 else "assets/images/futuristic-city.png"
image_name = os.path.basename(image_path)

print(f"Uploading {image_path} to {ghost_url}...")

with open(image_path, "rb") as f:
    resp = httpx.post(
        f"{ghost_url}/ghost/api/admin/images/upload/",
        headers={"Authorization": f"Ghost {token}"},
        files={"file": (image_name, f, "image/png")},
        data={"purpose": "image"},
        timeout=30.0,
    )

print(f"Status: {resp.status_code}")
data = resp.json()
print(data)

if resp.status_code == 201 and "images" in data:
    url = data["images"][0]["url"]
    print(f"\nFEATURE_IMAGE_URL={url}")
