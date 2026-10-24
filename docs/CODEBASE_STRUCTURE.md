# Maintained application structure

`pipeline/main.py` preserves the established CLI and import API.
`pipeline/cli.py` is an additional CLI entry point. Both load the same environment.
Email-triggered work continues to call the compatibility exports.

| Location | Responsibility |
| --- | --- |
| `pipeline/workflows/` | Blog, research, publish, index and direct-agent execution |
| `pipeline/workflows/execution.py` | Agent retry, budget/fallback handling and title repair |
| `pipeline/workflows/evidence.py` | Research validation, cache eligibility and source sanitisation |
| `pipeline/integrations/` | External-service transport/authentication helpers; Ghost is the first extraction |
| `pipeline/tools/` | Agent-facing tools and content preparation |
| `pipeline/storage/` | Connection policy and explicit PostgreSQL migration runner |
| `pipeline/settings.py` | Shared environment-file loading without overriding exported values |
| `config/` | Agent models, prompts, limits, source policy and allowed senders |
| `infra/` | Service inventory, migration files and release/rollback procedures |
| `scripts/` | Maintained operational commands |
| `tests/` | Offline regression tests and explicitly marked live integration tests |
| `archive/` | Historical notes; private scripts remain ignored under `archive/local/` |

Keep the Python package named `pipeline`; the installed SDK owns the top-level
`agents` package. Reusable service code belongs in integrations rather than
being duplicated inside tool decorators. Ghost is the initial extraction;
LinkedIn and newsletter clients remain in their existing modules for now.

Older design documents describe historical decisions. Use README.md for setup,
AGENTS.md for operational rules and infra/README.md for deployment procedures.
