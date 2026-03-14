"""
pipeline/config_loader.py — Load and validate YAML configuration files.

Reads all config files from the config/ directory at the project root
and returns merged configuration with sensible defaults for missing keys.

Usage::

    from pipeline.config_loader import load_config, get_limits, get_models

    config = load_config()
    timeout = config["limits"]["fetch"]["request_timeout_seconds"]
"""

import copy
import yaml
from pathlib import Path
from typing import Any, Optional

_CONFIG_DIR = Path(__file__).parent.parent / "config"

# ---------------------------------------------------------------------------
# Default values applied when keys are absent from the YAML files.
# These match production values (not testing-mode minimums).
# ---------------------------------------------------------------------------

_LIMIT_DEFAULTS: dict[str, Any] = {
    "budget": {
        "max_llm_calls_per_day": 500,
        "max_tokens_per_day": 100_000,
        "max_tasks_per_day": 20,
        "max_fetches_per_day": 200,
    },
    "fetch": {
        "max_pages_per_query": 8,
        "max_pages_per_task": 25,
        "max_content_chars_per_page": 16_000,
        "request_timeout_seconds": 15,
        "max_concurrent_fetches": 5,
        "per_domain_delay_seconds": 1.0,
    },
    "search": {
        "max_search_calls_per_task": 10,
        "duckduckgo": {"default_max_results": 10, "hard_max_results": 20},
        "arxiv": {"default_max_results": 5, "hard_max_results": 10},
        "corpus": {
            "default_top_k": 5,
            "hard_max_top_k": 20,
            "min_similarity_threshold": 0.40,
        },
    },
    "synthesis": {
        "max_draft_tokens": 4000,
        "max_edit_tokens": 4000,
        "max_research_output_tokens": 8000,
        "max_key_findings": 10,
        "max_sources_cited": 20,
    },
    "task": {
        "max_tool_calls_per_run": 50,
        "max_turns": 30,
        "max_handoffs": 5,
        "task_timeout_seconds": 600,
    },
    "chunking": {
        "max_words_per_chunk": 200,
        "overlap_words": 30,
    },
}

_MODEL_DEFAULTS: dict[str, Any] = {
    "agents": {},
    "fallback_chain": [
        "openai/gpt-5",
        "openai/gpt-4.1",
        "openai/gpt-5-mini",
        "openai/gpt-4.1-mini",
        "openai/gpt-4.1-nano",
    ],
    "degradation": {
        "soft_threshold_pct": 80,
        "hard_threshold_pct": 95,
    },
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Merge *override* into *base* recursively.

    Keys present in *override* overwrite *base*. Nested dicts are merged
    recursively rather than replaced wholesale. Modifies *base* in place
    and returns it.
    """
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_yaml(path: Path) -> dict:
    """Load a single YAML file; return empty dict if the file does not exist
    or contains only null/empty content."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(config_dir: Optional[Path] = None) -> dict[str, Any]:
    """Load all config YAML files and return a merged configuration dict.

    Missing files return empty dicts for their section. Missing keys within
    *limits.yaml* and *models.yaml* are filled in from built-in defaults so
    consumers can safely access any documented key without guarding.

    Args:
        config_dir: Path to the config directory. Defaults to
            ``<project_root>/config``. Pass a custom path in tests.

    Returns:
        Dict with keys: ``limits``, ``models``, ``sources``,
        ``allowlist``, ``prompts``.
    """
    d = _CONFIG_DIR if config_dir is None else Path(config_dir)

    limits = _deep_merge(copy.deepcopy(_LIMIT_DEFAULTS), _load_yaml(d / "limits.yaml"))
    models = _deep_merge(copy.deepcopy(_MODEL_DEFAULTS), _load_yaml(d / "models.yaml"))
    sources = _load_yaml(d / "sources.yaml")
    allowlist = _load_yaml(d / "allowlist.yaml")
    prompts = _load_yaml(d / "prompts.yaml")

    return {
        "limits": limits,
        "models": models,
        "sources": sources,
        "allowlist": allowlist,
        "prompts": prompts,
    }


def get_limits(config_dir: Optional[Path] = None) -> dict:
    """Convenience wrapper — returns just the ``limits`` section."""
    return load_config(config_dir)["limits"]


def get_models(config_dir: Optional[Path] = None) -> dict:
    """Convenience wrapper — returns just the ``models`` section."""
    return load_config(config_dir)["models"]


def get_allowlist(config_dir: Optional[Path] = None) -> dict:
    """Convenience wrapper — returns just the ``allowlist`` section."""
    return load_config(config_dir)["allowlist"]


def get_sources(config_dir: Optional[Path] = None) -> dict:
    """Convenience wrapper — returns just the ``sources`` section."""
    return load_config(config_dir)["sources"]
