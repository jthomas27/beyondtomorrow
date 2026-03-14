"""
tests/test_config_loader.py — Unit tests for pipeline/config_loader.py

Covers:
    load_config     — returns all five config sections, applies defaults for
                      missing keys, handles missing files gracefully
    _deep_merge     — recursively merges dicts without clobbering sibling keys
    get_limits      — convenience wrapper returns limits section
    get_models      — convenience wrapper returns models section
    get_allowlist   — convenience wrapper returns allowlist section
    get_sources     — convenience wrapper returns sources section
"""

import yaml
import pytest
from pathlib import Path

from pipeline.config_loader import (
    load_config,
    get_limits,
    get_models,
    get_allowlist,
    get_sources,
    _deep_merge,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(directory: Path, name: str, data: dict) -> None:
    """Write *data* as YAML to *directory/name*."""
    (directory / name).write_text(yaml.dump(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# load_config — against the real config/ directory
# ---------------------------------------------------------------------------

def test_load_config_returns_all_five_sections():
    """load_config() returns a dict with the five expected top-level keys."""
    config = load_config()
    for key in ("limits", "models", "sources", "allowlist", "prompts"):
        assert key in config, f"Missing section: {key}"


def test_limits_section_has_budget_key():
    config = load_config()
    assert "budget" in config["limits"]


def test_limits_section_has_fetch_key():
    config = load_config()
    assert "fetch" in config["limits"]


def test_limits_section_has_task_key():
    config = load_config()
    assert "task" in config["limits"]


def test_models_section_has_agents_key():
    config = load_config()
    assert "agents" in config["models"]


def test_models_section_has_fallback_chain():
    config = load_config()
    chain = config["models"]["fallback_chain"]
    assert isinstance(chain, list)
    assert len(chain) > 0


def test_models_agents_includes_researcher():
    config = load_config()
    assert "researcher" in config["models"]["agents"]


def test_models_researcher_has_model_field():
    config = load_config()
    assert "model" in config["models"]["agents"]["researcher"]


def test_allowlist_has_allowed_senders():
    config = load_config()
    assert "allowed_senders" in config["allowlist"]


# ---------------------------------------------------------------------------
# load_config — defaults applied when keys are absent (tmp_path)
# ---------------------------------------------------------------------------

def test_defaults_applied_for_missing_budget_key(tmp_path):
    """A limits.yaml without 'budget' gets the default budget section."""
    _write_yaml(tmp_path, "limits.yaml", {"fetch": {"max_pages_per_query": 5}})
    config = load_config(config_dir=tmp_path)
    # Default budget should be filled in
    assert "budget" in config["limits"]
    assert config["limits"]["budget"]["max_llm_calls_per_day"] == 500


def test_yaml_values_override_defaults(tmp_path):
    """Explicit values in limits.yaml override the built-in defaults."""
    _write_yaml(
        tmp_path,
        "limits.yaml",
        {"budget": {"max_llm_calls_per_day": 99}},
    )
    config = load_config(config_dir=tmp_path)
    assert config["limits"]["budget"]["max_llm_calls_per_day"] == 99
    # Other budget keys should still have defaults
    assert "max_tasks_per_day" in config["limits"]["budget"]


def test_missing_limits_file_returns_all_defaults(tmp_path):
    """When limits.yaml does not exist, all limits default to production values."""
    config = load_config(config_dir=tmp_path)
    assert config["limits"]["fetch"]["max_pages_per_query"] == 8
    assert config["limits"]["task"]["task_timeout_seconds"] == 600


def test_missing_models_file_returns_defaults(tmp_path):
    """When models.yaml does not exist, model defaults are applied."""
    config = load_config(config_dir=tmp_path)
    assert "fallback_chain" in config["models"]
    chain = config["models"]["fallback_chain"]
    assert "openai/gpt-5" in chain
    assert "openai/gpt-5-nano" in chain


def test_missing_sources_file_returns_empty_dict(tmp_path):
    """sources.yaml absent → empty dict (no defaults for sources)."""
    config = load_config(config_dir=tmp_path)
    assert config["sources"] == {}


def test_missing_prompts_file_returns_empty_dict(tmp_path):
    """prompts.yaml absent → empty dict."""
    config = load_config(config_dir=tmp_path)
    assert config["prompts"] == {}


def test_null_yaml_file_treated_as_empty(tmp_path):
    """A YAML file containing only 'null' is treated as an empty dict."""
    (tmp_path / "sources.yaml").write_text("null\n", encoding="utf-8")
    config = load_config(config_dir=tmp_path)
    assert config["sources"] == {}


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------

def test_deep_merge_overwrites_scalar_value():
    base = {"a": 1, "b": 2}
    _deep_merge(base, {"a": 99})
    assert base["a"] == 99
    assert base["b"] == 2  # untouched


def test_deep_merge_recursively_merges_nested_dicts():
    base = {"outer": {"a": 1, "b": 2}}
    _deep_merge(base, {"outer": {"b": 99, "c": 3}})
    assert base["outer"]["a"] == 1   # preserved
    assert base["outer"]["b"] == 99  # overridden
    assert base["outer"]["c"] == 3   # added


def test_deep_merge_adds_new_top_level_key():
    base = {"x": 1}
    _deep_merge(base, {"y": 2})
    assert base["y"] == 2


def test_deep_merge_does_not_mutate_override():
    base = {"a": {"x": 1}}
    override = {"a": {"y": 2}}
    _deep_merge(base, override)
    # override should not have gained 'x'
    assert "x" not in override["a"]


def test_deep_merge_scalar_override_replaces_dict():
    """If override has a scalar where base has a dict, scalar wins."""
    base = {"a": {"nested": 1}}
    _deep_merge(base, {"a": "flat"})
    assert base["a"] == "flat"


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------

def test_get_limits_returns_limits_section():
    limits = get_limits()
    assert "budget" in limits
    assert "fetch" in limits


def test_get_models_returns_models_section():
    models = get_models()
    assert "agents" in models
    assert "fallback_chain" in models


def test_get_allowlist_returns_allowlist_section():
    allowlist = get_allowlist()
    assert "allowed_senders" in allowlist


def test_get_sources_returns_sources_section():
    sources = get_sources()
    assert isinstance(sources, dict)
