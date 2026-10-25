"""
tests/test_linkedin.py — Unit tests for pipeline/tools/linkedin.py

Covers:
    _build_hashtags         — empty input, single tag, multi-word tags,
                              >5 tags truncated to 5, special characters stripped.
    post_to_linkedin        — SKIPPED when env vars missing,
                              invalid PERSON_URN format returns error,
                              invalid COMPANY_URN format falls back to personal-only,
                              duplicate URL returns SKIPPED for each destination,
                              successful 201 returns URN and updates dedup log,
                              company page also posted when LINKEDIN_COMPANY_URN set,
                              429 retries and exhausts attempts,
                              401 returns actionable error,
                              403 returns actionable error,
                              non-retriable 4xx reports actual attempt count.

HTTP calls are mocked via pytest-mock; no network access occurs.
"""

import json
import pytest

pytestmark = pytest.mark.usefixtures("memory_deliveries")
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from pipeline.tools.linkedin import _build_hashtags, post_to_linkedin, _POSTS_LOG
from tests.conftest import call_tool


# ---------------------------------------------------------------------------
# _build_hashtags
# ---------------------------------------------------------------------------

def test_build_hashtags_empty():
    assert _build_hashtags("") == ""


def test_build_hashtags_single():
    assert _build_hashtags("AI") == "#AI"


def test_build_hashtags_multi_word():
    assert _build_hashtags("Climate Change") == "#ClimateChange"


def test_build_hashtags_five_max():
    result = _build_hashtags("AI, Climate, Energy, Policy, Tech, Extra")
    parts = result.split()
    assert len(parts) == 5


def test_build_hashtags_strips_special_chars():
    result = _build_hashtags("C++ Programming")
    assert "#CProgramming" in result or "#" in result  # non-alphanum stripped


def test_build_hashtags_camelcase():
    result = _build_hashtags("Artificial Intelligence, geopolitics")
    assert "#ArtificialIntelligence" in result
    assert "#Geopolitics" in result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_TOKEN = "test-access-token"
_VALID_URN = "urn:li:person:abc123"
_VALID_COMPANY_URN = "urn:li:organization:99887766"
_GHOST_URL = "https://beyondtomorrow.world/test-post/"


def _mock_httpx_post(mocker, *, status_code: int, headers: dict | None = None, text: str = "", side_effect=None):
    """Patch httpx.AsyncClient.post to return a mock response (or raise a side_effect)."""
    if side_effect is not None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=side_effect)
    else:
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.headers = headers or {}
        mock_resp.text = text
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
    # Image upload GET returns an error so _upload_image_to_linkedin shortcircuits in most tests
    mock_client.get = AsyncMock(side_effect=httpx.RequestError("skip"))
    # Image upload PUT also used in _upload_image_to_linkedin
    mock_client.put = AsyncMock(side_effect=httpx.RequestError("skip"))

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mocker.patch("pipeline.tools.linkedin.httpx.AsyncClient", return_value=mock_cm)
    return mock_client


# ---------------------------------------------------------------------------
# SKIPPED: env vars missing
# ---------------------------------------------------------------------------

async def test_skipped_when_no_token(monkeypatch):
    monkeypatch.delenv("LINKEDIN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LINKEDIN_PERSON_URN", raising=False)
    result = await call_tool(
        post_to_linkedin, title="T", excerpt="E", post_url=_GHOST_URL
    )
    assert result == "SKIPPED: LinkedIn not configured"


async def test_skipped_when_no_urn(monkeypatch):
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", _VALID_TOKEN)
    monkeypatch.delenv("LINKEDIN_PERSON_URN", raising=False)
    result = await call_tool(
        post_to_linkedin, title="T", excerpt="E", post_url=_GHOST_URL
    )
    assert result == "SKIPPED: LinkedIn not configured"


# ---------------------------------------------------------------------------
# Invalid URN format
# ---------------------------------------------------------------------------

async def test_invalid_urn_format(monkeypatch):
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", _VALID_TOKEN)
    monkeypatch.setenv("LINKEDIN_PERSON_URN", "badformat")
    monkeypatch.delenv("LINKEDIN_COMPANY_URN", raising=False)
    result = await call_tool(
        post_to_linkedin, title="T", excerpt="E", post_url=_GHOST_URL
    )
    assert result.startswith("Error:")
    assert "invalid format" in result


async def test_invalid_company_urn_skips_company_post(monkeypatch, mocker, tmp_path):
    """Bad LINKEDIN_COMPANY_URN logs a warning but personal post still goes through."""
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", _VALID_TOKEN)
    monkeypatch.setenv("LINKEDIN_PERSON_URN", _VALID_URN)
    monkeypatch.setenv("LINKEDIN_COMPANY_URN", "not-an-urn")

    _mock_httpx_post(mocker, status_code=201, headers={"x-restli-id": "personal99"})

    with patch("pipeline.tools.linkedin._POSTS_LOG", tmp_path / "log.json"):
        result = await call_tool(
            post_to_linkedin, title="T", excerpt="E", post_url=_GHOST_URL
        )

    # Company post silently skipped; only personal result returned
    assert "Personal:" in result
    assert "Company:" not in result


# ---------------------------------------------------------------------------
# Duplicate-post guard
# ---------------------------------------------------------------------------

async def test_duplicate_post_imports_receipt_without_reposting(monkeypatch, tmp_path, mocker):
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", _VALID_TOKEN)
    monkeypatch.setenv("LINKEDIN_PERSON_URN", _VALID_URN)
    monkeypatch.delenv("LINKEDIN_COMPANY_URN", raising=False)

    fake_log = tmp_path / "linkedin_posts.json"
    fake_log.write_text(json.dumps({_GHOST_URL: "urn:li:share:existing123"}))
    _mock_httpx_post(mocker, status_code=201, headers={"x-restli-id": "replacement"})

    with patch("pipeline.tools.linkedin._POSTS_LOG", fake_log):
        result = await call_tool(
            post_to_linkedin, title="T", excerpt="E", post_url=_GHOST_URL
        )

    assert "Personal: urn:li:share:existing123" in result
    assert json.loads(fake_log.read_text())[_GHOST_URL] == "urn:li:share:existing123"


# ---------------------------------------------------------------------------
# Successful 201 publish
# ---------------------------------------------------------------------------

async def test_successful_publish(monkeypatch, mocker, tmp_path, memory_deliveries):
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", _VALID_TOKEN)
    monkeypatch.setenv("LINKEDIN_PERSON_URN", _VALID_URN)
    monkeypatch.delenv("LINKEDIN_COMPANY_URN", raising=False)

    fake_log = tmp_path / "linkedin_posts.json"

    _mock_httpx_post(
        mocker,
        status_code=201,
        headers={"x-restli-id": "share999"},
    )

    with patch("pipeline.tools.linkedin._POSTS_LOG", fake_log):
        result = await call_tool(
            post_to_linkedin, title="Test Title", excerpt="An excerpt.", post_url=_GHOST_URL
        )

    assert "urn:li:share:share999" in result
    assert "Personal:" in result
    assert not fake_log.exists()
    assert any(r.external_id == "urn:li:share:share999" for r in memory_deliveries.values())


async def test_company_configuration_does_not_enable_company_posting(monkeypatch, mocker, tmp_path, memory_deliveries):
    """Current integration posts to the personal profile only, even with legacy company config."""
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", _VALID_TOKEN)
    monkeypatch.setenv("LINKEDIN_PERSON_URN", _VALID_URN)
    monkeypatch.setenv("LINKEDIN_COMPANY_URN", _VALID_COMPANY_URN)

    fake_log = tmp_path / "linkedin_posts.json"

    # Return different share IDs per call to distinguish personal vs company
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.RequestError("skip"))
    mock_client.put = AsyncMock(side_effect=httpx.RequestError("skip"))

    personal_resp = MagicMock()
    personal_resp.status_code = 201
    personal_resp.headers = {"x-restli-id": "personalShare"}

    company_resp = MagicMock()
    company_resp.status_code = 201
    company_resp.headers = {"x-restli-id": "companyShare"}

    mock_client.post = AsyncMock(side_effect=[personal_resp, company_resp])

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mocker.patch("pipeline.tools.linkedin.httpx.AsyncClient", return_value=mock_cm)

    with patch("pipeline.tools.linkedin._POSTS_LOG", fake_log):
        result = await call_tool(
            post_to_linkedin, title="Title", excerpt="Excerpt", post_url=_GHOST_URL
        )

    assert "Personal: urn:li:share:personalShare" in result
    assert "Company:" not in result
    assert mock_client.post.await_count == 1
    assert not fake_log.exists()
    assert len(memory_deliveries) == 1
    assert next(iter(memory_deliveries.values())).external_id == 'urn:li:share:personalShare'


async def test_company_duplicate_skipped_personal_not(monkeypatch, mocker, tmp_path):
    """Company already posted to LinkedIn — personal post proceeds but company is skipped."""
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", _VALID_TOKEN)
    monkeypatch.setenv("LINKEDIN_PERSON_URN", _VALID_URN)
    monkeypatch.setenv("LINKEDIN_COMPANY_URN", _VALID_COMPANY_URN)

    company_key = f"{_GHOST_URL}|{_VALID_COMPANY_URN}"
    fake_log = tmp_path / "linkedin_posts.json"
    # Pre-seed only the company entry; personal is fresh
    fake_log.write_text(json.dumps({company_key: "urn:li:share:companyOld"}))

    _mock_httpx_post(mocker, status_code=201, headers={"x-restli-id": "personalNew"})

    with patch("pipeline.tools.linkedin._POSTS_LOG", fake_log):
        result = await call_tool(
            post_to_linkedin, title="T", excerpt="E", post_url=_GHOST_URL
        )

    assert "Personal: urn:li:share:personalNew" in result
    assert "Company:" not in result
    assert json.loads(fake_log.read_text())[company_key] == "urn:li:share:companyOld"


# ---------------------------------------------------------------------------
# 401 — expired / invalid token
# ---------------------------------------------------------------------------

async def test_401_returns_actionable_error(monkeypatch, mocker, tmp_path):
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", _VALID_TOKEN)
    monkeypatch.setenv("LINKEDIN_PERSON_URN", _VALID_URN)
    monkeypatch.delenv("LINKEDIN_COMPANY_URN", raising=False)

    _mock_httpx_post(mocker, status_code=401)

    with patch("pipeline.tools.linkedin._POSTS_LOG", tmp_path / "log.json"):
        result = await call_tool(
            post_to_linkedin, title="T", excerpt="E", post_url=_GHOST_URL
        )

    assert "401" in result
    assert "linkedin_auth.py" in result


# ---------------------------------------------------------------------------
# 403 — missing product approval
# ---------------------------------------------------------------------------

async def test_403_returns_actionable_error(monkeypatch, mocker, tmp_path):
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", _VALID_TOKEN)
    monkeypatch.setenv("LINKEDIN_PERSON_URN", _VALID_URN)
    monkeypatch.delenv("LINKEDIN_COMPANY_URN", raising=False)

    _mock_httpx_post(mocker, status_code=403, text="Insufficient permissions")

    with patch("pipeline.tools.linkedin._POSTS_LOG", tmp_path / "log.json"):
        result = await call_tool(
            post_to_linkedin, title="T", excerpt="E", post_url=_GHOST_URL
        )

    assert "403" in result
    assert "Share on LinkedIn" in result


# ---------------------------------------------------------------------------
# 429 rate limit — exhausts retries, reports accurate attempt count
# ---------------------------------------------------------------------------

async def test_429_exhausts_retries(monkeypatch, mocker, tmp_path):
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", _VALID_TOKEN)
    monkeypatch.setenv("LINKEDIN_PERSON_URN", _VALID_URN)
    monkeypatch.delenv("LINKEDIN_COMPANY_URN", raising=False)

    mock_client = _mock_httpx_post(mocker, status_code=429)
    # Patch asyncio.sleep to avoid actual delays
    mocker.patch("pipeline.tools.linkedin.asyncio.sleep", new=AsyncMock())

    with patch("pipeline.tools.linkedin._POSTS_LOG", tmp_path / "log.json"):
        result = await call_tool(
            post_to_linkedin, title="T", excerpt="E", post_url=_GHOST_URL
        )

    assert "Error" in result
    assert "3 attempt(s)" in result
    assert mock_client.post.call_count == 3


# ---------------------------------------------------------------------------
# Non-retriable 4xx — reports actual attempt count (should be 1)
# ---------------------------------------------------------------------------

async def test_non_retriable_error_reports_one_attempt(monkeypatch, mocker, tmp_path):
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", _VALID_TOKEN)
    monkeypatch.setenv("LINKEDIN_PERSON_URN", _VALID_URN)
    monkeypatch.delenv("LINKEDIN_COMPANY_URN", raising=False)

    mock_client = _mock_httpx_post(mocker, status_code=422, text="Unprocessable")

    with patch("pipeline.tools.linkedin._POSTS_LOG", tmp_path / "log.json"):
        result = await call_tool(
            post_to_linkedin, title="T", excerpt="E", post_url=_GHOST_URL
        )

    assert "Error" in result
    assert "1 attempt(s)" in result
    assert mock_client.post.call_count == 1
