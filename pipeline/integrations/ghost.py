"""Ghost HTTP retry policy and short-lived Admin JWT authentication."""
import asyncio
import logging
import time
import httpx
import jwt

logger = logging.getLogger(__name__)
_GHOST_RETRY_ATTEMPTS = 3
_GHOST_RETRY_DELAYS = [2, 4, 8]

def create_admin_token(admin_key: str) -> str:
    key_id, secret = admin_key.split(":", 1)
    now = int(time.time())
    return jwt.encode({"iat": now, "exp": now + 300, "aud": "/admin/"},
                      bytes.fromhex(secret), algorithm="HS256",
                      headers={"alg": "HS256", "typ": "JWT", "kid": key_id})

async def _ghost_post_with_retry(client: httpx.AsyncClient, url: str, json_data: dict, headers: dict) -> httpx.Response:
    """POST to Ghost Admin API with retry + exponential backoff."""
    last_exc: Exception | None = None
    for attempt in range(_GHOST_RETRY_ATTEMPTS):
        try:
            resp = await client.post(url, json=json_data, headers=headers)
            resp.raise_for_status()
            return resp
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < _GHOST_RETRY_ATTEMPTS - 1:
                delay = _GHOST_RETRY_DELAYS[attempt]
                logger.warning("Ghost API attempt %d failed (%s), retrying in %ds...", attempt + 1, exc, delay)
                await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]

