# Maintained application structure

`pipeline/main.py` preserves the established CLI and import API.
`pipeline/cli.py` is an additional CLI entry point. Both load the same environment.
Email-triggered work continues to call the compatibility exports.

| Location | Responsibility |
| --- | --- |
| `.agents/skills/` | Project Codex workflows and on-demand references |
| `pipeline/workflows/` | Blog, research, publish, index and direct-agent execution |
| `pipeline/workflows/execution.py` | Agent retry, budget/fallback handling and title repair |
| `pipeline/workflows/evidence.py` | Research validation, cache eligibility and source sanitisation |
| `pipeline/integrations/` | External-service transport/authentication helpers; Ghost is the first extraction |
| `pipeline/tools/` | Agent-facing tools and content preparation |
| `pipeline/storage/` | Connection policy, explicit migrations, durable email jobs and delivery receipts |
| `pipeline/workflows/results.py` | Explicit workflow statuses and CLI exit codes |
| `pipeline/settings.py` | Shared environment-file loading without overriding exported values |
| `config/` | Agent models, prompts, limits, source policy and allowed senders |
| `infra/` | Service inventory, migration files and release/rollback procedures |
| `scripts/` | Maintained operational commands |
| `tests/` | Offline regression tests and explicitly marked live integration tests |
| `theme/src/` | Maintained appearance templates, CSS and JavaScript |
| `theme/header.txt`, `theme/footer.txt` | Generated Ghost injection artifacts |
| `archive/` | Historical notes; private scripts remain ignored under `archive/local/` |

Keep the Python package named `pipeline`; the installed SDK owns the top-level
`agents` package. Reusable service code belongs in integrations rather than
being duplicated inside tool decorators. Ghost is the initial extraction;
LinkedIn and newsletter clients remain in their existing modules for now.

Older design documents describe historical decisions. Use README.md for setup,
AGENTS.md for operational rules and infra/README.md for deployment procedures.

Codex-specific workspace guidance is in [CODEX_WORKFLOW.md](CODEX_WORKFLOW.md).
Delivery and retry behaviour is documented in [DELIVERY_RECOVERY.md](DELIVERY_RECOVERY.md).
