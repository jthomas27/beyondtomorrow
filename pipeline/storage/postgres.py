"""PostgreSQL connection options shared by runtime and migration commands."""
from urllib.parse import parse_qs, urlparse


def ssl_for_url(url: str):
    parsed = urlparse(url)
    mode = (parse_qs(parsed.query).get("sslmode") or [""])[0].lower()
    return "require" if mode in {"require", "verify-ca", "verify-full"} else False
