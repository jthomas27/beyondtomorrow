"""
tests/test_setup.py — Unit tests for pipeline/setup.py

Covers:
    init_github_models  — raises RuntimeError when GITHUB_TOKEN is missing,
                          returns an AsyncOpenAI client with the correct
                          base URL, and calls the SDK registration helpers.
"""

import pytest
from openai import AsyncOpenAI

from pipeline.setup import init_github_models


# ---------------------------------------------------------------------------
# init_github_models
# ---------------------------------------------------------------------------

def test_init_raises_without_github_token(monkeypatch):
    """RuntimeError is raised when GITHUB_TOKEN is not set."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
        init_github_models()


def test_init_returns_async_openai_client(monkeypatch, mocker):
    """A valid token produces an AsyncOpenAI client instance."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-abc")
    mocker.patch("pipeline.setup.set_default_openai_client")
    mocker.patch("pipeline.setup.set_default_openai_api")

    client = init_github_models()
    assert isinstance(client, AsyncOpenAI)


def test_init_sets_github_models_base_url(monkeypatch, mocker):
    """The returned client points at the GitHub Models inference endpoint."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-abc")
    mocker.patch("pipeline.setup.set_default_openai_client")
    mocker.patch("pipeline.setup.set_default_openai_api")

    client = init_github_models()
    assert "models.github.ai" in str(client.base_url)


def test_init_calls_set_default_openai_client(monkeypatch, mocker):
    """set_default_openai_client is called once with the new client."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-abc")
    mock_set_client = mocker.patch("pipeline.setup.set_default_openai_client")
    mocker.patch("pipeline.setup.set_default_openai_api")

    client = init_github_models()
    mock_set_client.assert_called_once_with(client)


def test_init_sets_chat_completions_api(monkeypatch, mocker):
    """set_default_openai_api is called with 'chat_completions'."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-abc")
    mocker.patch("pipeline.setup.set_default_openai_client")
    mock_set_api = mocker.patch("pipeline.setup.set_default_openai_api")

    init_github_models()
    mock_set_api.assert_called_once_with("chat_completions")


def test_init_uses_token_as_api_key(monkeypatch, mocker):
    """The GITHUB_TOKEN value is used as the AsyncOpenAI api_key."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_my_test_token")
    mocker.patch("pipeline.setup.set_default_openai_client")
    mocker.patch("pipeline.setup.set_default_openai_api")

    client = init_github_models()
    assert client.api_key == "ghs_my_test_token"
