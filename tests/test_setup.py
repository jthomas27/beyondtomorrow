"""
tests/test_setup.py — Unit tests for pipeline/setup.py

Covers:
    init_openai  — raises RuntimeError when OPENAI_API_KEY is missing,
                   returns an AsyncOpenAI client pointed at api.openai.com,
                   and calls the SDK registration helpers.
"""

import pytest
from openai import AsyncOpenAI

from pipeline.setup import init_openai


# ---------------------------------------------------------------------------
# init_openai
# ---------------------------------------------------------------------------

def test_init_raises_without_openai_api_key(monkeypatch):
    """RuntimeError is raised when OPENAI_API_KEY is not set."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        init_openai()


def test_init_returns_async_openai_client(monkeypatch, mocker):
    """A valid key produces an AsyncOpenAI client instance."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-token-abc")
    mocker.patch("pipeline.setup.set_default_openai_client")
    mocker.patch("pipeline.setup.set_default_openai_api")

    client = init_openai()
    assert isinstance(client, AsyncOpenAI)


def test_init_sets_openai_base_url(monkeypatch, mocker):
    """The returned client points at the OpenAI API endpoint."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-token-abc")
    mocker.patch("pipeline.setup.set_default_openai_client")
    mocker.patch("pipeline.setup.set_default_openai_api")

    client = init_openai()
    assert "api.openai.com" in str(client.base_url)


def test_init_calls_set_default_openai_client(monkeypatch, mocker):
    """set_default_openai_client is called once with the new client."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-token-abc")
    mock_set_client = mocker.patch("pipeline.setup.set_default_openai_client")
    mocker.patch("pipeline.setup.set_default_openai_api")

    client = init_openai()
    mock_set_client.assert_called_once_with(client)


def test_init_sets_responses_api(monkeypatch, mocker):
    """set_default_openai_api is called with 'responses'."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-token-abc")
    mocker.patch("pipeline.setup.set_default_openai_client")
    mock_set_api = mocker.patch("pipeline.setup.set_default_openai_api")

    init_openai()
    mock_set_api.assert_called_once_with("responses")


def test_init_uses_key_as_api_key(monkeypatch, mocker):
    """The OPENAI_API_KEY value is used as the AsyncOpenAI api_key."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-my-test-key")
    mocker.patch("pipeline.setup.set_default_openai_client")
    mocker.patch("pipeline.setup.set_default_openai_api")

    client = init_openai()
    assert client.api_key == "sk-my-test-key"
