"""
tests/test_db.py — Unit tests for pipeline/db.py

Covers:
    get_pool              — raises RuntimeError when DATABASE_URL is absent,
                            creates a pool when URL is present, returns the
                            same pool object on repeated calls (singleton)
    close_pool            — closes the pool and resets the module-level cache
    _setup_vector_codec   — registers the pgvector text codec with correct
                            encoder/decoder callables
    SSL selection         — sslmode=require sets ssl to "require";
                            .railway.internal host sets ssl to False
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, call

import pipeline.db as db_module
from pipeline.db import _setup_vector_codec, get_pool, close_pool


# ---------------------------------------------------------------------------
# Fixture: reset the module-level _pool singleton between every test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_pool():
    """Ensure the singleton pool is None before and after each test."""
    db_module._pool = None
    yield
    db_module._pool = None


# ---------------------------------------------------------------------------
# get_pool
# ---------------------------------------------------------------------------

async def test_get_pool_raises_without_database_url(monkeypatch):
    """RuntimeError is raised when DATABASE_URL is not set."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        await get_pool()


async def test_get_pool_creates_pool_with_database_url(monkeypatch, mocker):
    """When DATABASE_URL is set, asyncpg.create_pool is called once."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/db")
    mock_pool = MagicMock()
    mock_create = mocker.patch(
        "pipeline.db.asyncpg.create_pool",
        new=AsyncMock(return_value=mock_pool),
    )

    result = await get_pool()

    mock_create.assert_called_once()
    assert result is mock_pool


async def test_get_pool_returns_singleton_on_second_call(monkeypatch, mocker):
    """A second call to get_pool returns the cached pool without re-creating."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/db")
    mock_pool = MagicMock()
    mock_create = mocker.patch(
        "pipeline.db.asyncpg.create_pool",
        new=AsyncMock(return_value=mock_pool),
    )

    pool1 = await get_pool()
    pool2 = await get_pool()

    assert pool1 is pool2
    mock_create.assert_called_once()  # only created once


# ---------------------------------------------------------------------------
# close_pool
# ---------------------------------------------------------------------------

async def test_close_pool_calls_close_and_resets(monkeypatch, mocker):
    """close_pool closes the existing pool and sets _pool back to None."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/db")
    mock_pool = AsyncMock()
    mocker.patch(
        "pipeline.db.asyncpg.create_pool",
        new=AsyncMock(return_value=mock_pool),
    )

    await get_pool()
    assert db_module._pool is not None

    await close_pool()

    mock_pool.close.assert_called_once()
    assert db_module._pool is None


async def test_close_pool_is_safe_when_no_pool_exists():
    """close_pool does nothing (no error) when called before any pool created."""
    assert db_module._pool is None
    await close_pool()  # should not raise


# ---------------------------------------------------------------------------
# _setup_vector_codec
# ---------------------------------------------------------------------------

async def test_setup_vector_codec_registers_type_codec(mocker):
    """_setup_vector_codec calls conn.set_type_codec with type='vector'."""
    mock_conn = AsyncMock()
    await _setup_vector_codec(mock_conn)
    mock_conn.set_type_codec.assert_called_once()
    args = mock_conn.set_type_codec.call_args
    assert args[0][0] == "vector"


async def test_setup_vector_codec_encoder_produces_bracket_format(mocker):
    """The registered encoder converts a Python list to '[x,y,z]' format."""
    mock_conn = AsyncMock()
    await _setup_vector_codec(mock_conn)
    encoder = mock_conn.set_type_codec.call_args[1]["encoder"]
    assert encoder([0.1, 0.2, 0.3]) == "[0.1,0.2,0.3]"


async def test_setup_vector_codec_decoder_parses_bracket_format(mocker):
    """The registered decoder converts '[x,y,z]' to a Python list of floats."""
    mock_conn = AsyncMock()
    await _setup_vector_codec(mock_conn)
    decoder = mock_conn.set_type_codec.call_args[1]["decoder"]
    result = decoder("[0.1,0.2,0.3]")
    assert len(result) == 3
    assert abs(result[0] - 0.1) < 1e-9
    assert abs(result[1] - 0.2) < 1e-9
    assert abs(result[2] - 0.3) < 1e-9


# ---------------------------------------------------------------------------
# SSL selection logic
# ---------------------------------------------------------------------------

async def test_ssl_require_for_sslmode_require(monkeypatch, mocker):
    """sslmode=require in the DATABASE_URL results in ssl='require'."""
    url = "postgresql://user:pass@host:5432/db?sslmode=require"
    monkeypatch.setenv("DATABASE_URL", url)
    mock_create = mocker.patch(
        "pipeline.db.asyncpg.create_pool",
        new=AsyncMock(return_value=MagicMock()),
    )

    await get_pool()

    _, kwargs = mock_create.call_args
    assert kwargs.get("ssl") == "require"


async def test_ssl_disabled_for_internal_railway_host(monkeypatch, mocker):
    """Internal Railway hosts (.railway.internal) disable SSL."""
    url = "postgresql://user:pass@my-service.railway.internal:5432/db"
    monkeypatch.setenv("DATABASE_URL", url)
    mock_create = mocker.patch(
        "pipeline.db.asyncpg.create_pool",
        new=AsyncMock(return_value=MagicMock()),
    )

    await get_pool()

    _, kwargs = mock_create.call_args
    assert kwargs.get("ssl") is False


async def test_ssl_disabled_when_no_sslmode(monkeypatch, mocker):
    """A plain DATABASE_URL with no sslmode disables SSL (TCP proxy default)."""
    url = "postgresql://user:pass@host:5432/db"
    monkeypatch.setenv("DATABASE_URL", url)
    mock_create = mocker.patch(
        "pipeline.db.asyncpg.create_pool",
        new=AsyncMock(return_value=MagicMock()),
    )

    await get_pool()

    _, kwargs = mock_create.call_args
    assert kwargs.get("ssl") is False
