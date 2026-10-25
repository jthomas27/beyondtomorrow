# Retired maintenance commands

These files preserve historical implementation details. They are not supported
operational commands and must not be executed. Some print credential values,
use an unsupported Railway API, modify Ghost's database directly, or migrate to
obsolete embedding dimensions.

Use `scripts/railway_variables.py`, `pipeline.storage.migrate`, the current
`scripts/migrate_embeddings.py`, and the runbooks in `infra/README.md` instead.
Theme deployment uses `scripts/deploy_ghost_theme.py` with private backups.
