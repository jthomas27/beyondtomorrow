"""
tests/test_ghost.py — Unit tests for pipeline/tools/ghost.py

Covers:
    publish_to_ghost  — missing env vars return error strings,
                        invalid key format returns error strings,
                        JWT is generated and sent as Authorization header,
                        tags are split and structured correctly,
                        HTTP errors are caught and returned as strings,
                        successful publish returns the post URL.

HTTP calls are mocked via pytest-mock; no network access occurs.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

import httpx

from pipeline.tools.ghost import publish_to_ghost
from tests.conftest import call_tool

# A key ID and valid hex secret (8 bytes = 16 hex chars) for JWT tests.
_VALID_KEY = "key123id:deadbeef12345678"
_GHOST_URL = "https://ghost.example.com"


def _make_mock_httpx(mocker, *, status_code=201, post_json=None):
    """Return a patched httpx.AsyncClient context manager mock."""
    if post_json is None:
        post_json = {
            "posts": [
                {
                    "title": "Test Post",
                    "url": "https://ghost.example.com/test-post/",
                    "status": "draft",
                }
            ]
        }
    mock_resp = MagicMock()
    mock_resp.json.return_value = post_json
    mock_resp.raise_for_status = MagicMock()

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_resp)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mocker.patch("pipeline.tools.ghost.httpx.AsyncClient", return_value=mock_cm)
    return mock_http, mock_resp


# ---------------------------------------------------------------------------
# Missing / malformed environment variables
# ---------------------------------------------------------------------------

async def test_missing_env_vars_returns_error(monkeypatch):
    """Both GHOST_URL and GHOST_ADMIN_KEY absent → error string."""
    monkeypatch.delenv("GHOST_URL", raising=False)
    monkeypatch.delenv("GHOST_ADMIN_KEY", raising=False)
    result = await call_tool(
        publish_to_ghost, title="T", html_content="<p>body</p>"
    )
    assert result.startswith("Error:")
    assert "GHOST_URL" in result


async def test_missing_ghost_url_returns_error(monkeypatch):
    """GHOST_URL absent (even with GHOST_ADMIN_KEY set) → error string."""
    monkeypatch.delenv("GHOST_URL", raising=False)
    monkeypatch.setenv("GHOST_ADMIN_KEY", _VALID_KEY)
    result = await call_tool(
        publish_to_ghost, title="T", html_content="<p>body</p>"
    )
    assert result.startswith("Error:")


async def test_invalid_key_format_no_colon_returns_error(monkeypatch):
    """GHOST_ADMIN_KEY without ':' separator → error string."""
    monkeypatch.setenv("GHOST_URL", _GHOST_URL)
    monkeypatch.setenv("GHOST_ADMIN_KEY", "invalidkeyformat")
    result = await call_tool(
        publish_to_ghost, title="T", html_content="<p>body</p>"
    )
    assert result.startswith("Error:")
    assert "id:secret" in result


# ---------------------------------------------------------------------------
# Successful publish
# ---------------------------------------------------------------------------

async def test_successful_publish_returns_post_url(monkeypatch, mocker):
    """A valid request returns the published post URL."""
    monkeypatch.setenv("GHOST_URL", _GHOST_URL)
    monkeypatch.setenv("GHOST_ADMIN_KEY", _VALID_KEY)
    _make_mock_httpx(mocker)

    result = await call_tool(
        publish_to_ghost,
        title="Test Post",
        html_content="<p>Hello world</p>",
    )
    assert "test-post" in result
    assert "draft" in result


async def test_publish_sends_post_to_ghost_api_endpoint(monkeypatch, mocker):
    """The HTTP POST is sent to /ghost/api/admin/posts/."""
    monkeypatch.setenv("GHOST_URL", _GHOST_URL)
    monkeypatch.setenv("GHOST_ADMIN_KEY", _VALID_KEY)
    mock_http, _ = _make_mock_httpx(mocker)

    await call_tool(
        publish_to_ghost,
        title="Test Post",
        html_content="<p>Hello</p>",
    )

    mock_http.post.assert_called_once()
    url_arg = mock_http.post.call_args[0][0]
    assert url_arg.endswith("/ghost/api/admin/posts/")


async def test_publish_includes_ghost_jwt_header(monkeypatch, mocker):
    """The Authorization header starts with 'Ghost '."""
    monkeypatch.setenv("GHOST_URL", _GHOST_URL)
    monkeypatch.setenv("GHOST_ADMIN_KEY", _VALID_KEY)
    mock_http, _ = _make_mock_httpx(mocker)

    await call_tool(
        publish_to_ghost,
        title="Test Post",
        html_content="<p>Hello</p>",
    )

    headers = mock_http.post.call_args[1]["headers"]
    assert headers["Authorization"].startswith("Ghost ")


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

async def test_tags_are_split_into_name_dicts(monkeypatch, mocker):
    """Comma-separated tags become [{'name': ...}, ...] in the post payload."""
    monkeypatch.setenv("GHOST_URL", _GHOST_URL)
    monkeypatch.setenv("GHOST_ADMIN_KEY", _VALID_KEY)
    mock_http, _ = _make_mock_httpx(mocker)

    await call_tool(
        publish_to_ghost,
        title="Test Post",
        html_content="<p>Hello</p>",
        tags="technology, AI, quantum",
    )

    post_body = mock_http.post.call_args[1]["json"]
    tags_sent = post_body["posts"][0]["tags"]
    assert tags_sent == [
        {"name": "technology"},
        {"name": "AI"},
        {"name": "quantum"},
    ]


async def test_empty_tags_produces_empty_tag_list(monkeypatch, mocker):
    """Passing tags='' results in an empty tags list in the payload."""
    monkeypatch.setenv("GHOST_URL", _GHOST_URL)
    monkeypatch.setenv("GHOST_ADMIN_KEY", _VALID_KEY)
    mock_http, _ = _make_mock_httpx(mocker)

    await call_tool(
        publish_to_ghost,
        title="Test Post",
        html_content="<p>Hello</p>",
        tags="",
    )

    post_body = mock_http.post.call_args[1]["json"]
    assert post_body["posts"][0]["tags"] == []


async def test_default_status_is_draft(monkeypatch, mocker):
    """When status is omitted the post is created as a draft."""
    monkeypatch.setenv("GHOST_URL", _GHOST_URL)
    monkeypatch.setenv("GHOST_ADMIN_KEY", _VALID_KEY)
    mock_http, _ = _make_mock_httpx(mocker)

    await call_tool(
        publish_to_ghost,
        title="Test Post",
        html_content="<p>Hello</p>",
    )

    post_body = mock_http.post.call_args[1]["json"]
    assert post_body["posts"][0]["status"] == "draft"


async def test_excerpt_included_in_payload(monkeypatch, mocker):
    """A custom excerpt is forwarded as 'custom_excerpt' in the payload."""
    monkeypatch.setenv("GHOST_URL", _GHOST_URL)
    monkeypatch.setenv("GHOST_ADMIN_KEY", _VALID_KEY)
    mock_http, _ = _make_mock_httpx(mocker)

    await call_tool(
        publish_to_ghost,
        title="Test Post",
        html_content="<p>Hello</p>",
        excerpt="A short description.",
    )

    post_body = mock_http.post.call_args[1]["json"]
    assert post_body["posts"][0]["custom_excerpt"] == "A short description."


# ---------------------------------------------------------------------------
# HTTP error handling
# ---------------------------------------------------------------------------

async def test_http_error_returns_error_string(monkeypatch, mocker):
    """An httpx.HTTPError is caught and returned as a human-readable string."""
    monkeypatch.setenv("GHOST_URL", _GHOST_URL)
    monkeypatch.setenv("GHOST_ADMIN_KEY", _VALID_KEY)

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(
        side_effect=httpx.HTTPError("connection refused")
    )
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mocker.patch("pipeline.tools.ghost.httpx.AsyncClient", return_value=mock_cm)

    result = await call_tool(
        publish_to_ghost,
        title="Test Post",
        html_content="<p>Hello</p>",
    )
    assert result.startswith("Failed to publish")
    assert "connection refused" in result
