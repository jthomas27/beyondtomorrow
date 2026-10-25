# Deployment and database operations

The worker configuration is [railway.toml](../railway.toml). Ghost uses its
own Docker service; do not deploy the worker configuration to Ghost.
[services.json](services.json) records reviewed service IDs, images and mounts.
It contains no credentials and is not an automatic infrastructure reconciler.

## Worker release

1. Run tests for the changed components. Python 3.11 is the declared development,
   CI and deployment target; an existing local environment must be checked
   separately before changing its interpreter.
2. Preview pending PostgreSQL migration files:
   `.venv/bin/python -m pipeline.storage.migrate`.
3. If schema changes are part of the release, back up PostgreSQL and run
   `.venv/bin/python -m pipeline.storage.migrate --apply` before starting code
   that requires them. This command writes only to PostgreSQL, not Ghost MySQL.
4. Deploy the worker once and perform one status check. If still building,
   report that state. Do not repeatedly poll or send test publications/emails.

Prefer the connected GitHub `main` release path after a requested commit/push.
It avoids the direct CLI upload limit encountered with the image asset library.
If an exceptional source upload needs a compact bundle, the existing
`scripts/restore_release_assets.py` can restore images listed in a generated
`release-manifest.json`: include SHA-256 checksums only for files unchanged from
the script's immutable upstream revision, and include any changed/new assets in
the bundle. Preserve the originals locally. Do not upload `.env`, logs, private
backups or dependency directories. `.railwayignore` records exclusions.

The initial SQL migration creates the current 1536-dimensional corpus tables
on an empty PostgreSQL database and adopts existing compatible objects with
`IF NOT EXISTS`. It does not convert incompatible legacy table layouts or
re-embed documents. Review existing schemas before adoption. Migration files
are applied transactionally under an advisory lock and recorded with checksums;
add a new file instead of changing an applied file.

Pool creation no longer creates tables or indexes. Existing deployments retain
their existing objects; fresh databases require the explicit migration command.

Migration `0002_delivery_and_email_jobs.sql` adds durable requests, publication
receipts and recipient delivery state. Apply it before deploying the hardened
worker. See [delivery recovery](../docs/DELIVERY_RECOVERY.md) for lease recovery,
explicit retries, sender authentication and ambiguous provider outcomes.

## Ghost/MySQL upgrades

Follow [AGENTS.md](../AGENTS.md) and the current private migration record,
retained locally with operational evidence.
Preserve the source database/content, migrate into a separate database, validate
content and credentials, and retain matching rollback settings privately.

Inspect whether a source change already created a deployment before requesting
another. Never interrupt an active schema migration with a second deployment.
If startup reports a migration lock, stop concurrent instances, inspect active
database commands and migration state, and preserve evidence before repair.

## Rollback

For a worker rollback, restore a known-good release compatible with the current
schema. Destructive schema downgrades are not automatic. Validate that the
matching credentials and model configuration are still usable.

For Ghost, restore the matching Ghost image, database and content snapshot as
one unit. Never point an older Ghost image at an upgraded schema. The legacy
MySQL server is write-protected: restoration must explicitly account for that
protection and the rotated credentials. Rollback secrets remain under private,
gitignored operational storage, not in this inventory.

The service named `ghost-mysql8-validation` is the live MySQL service. The
separate `ghost-validation` application was temporary. Do not confuse them.
