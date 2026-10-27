# Railway cost controls

Reviewed 26 October 2026. Live services are Ghost, `ghost-mysql8-validation`,
pgvector and email-worker. The MySQL service name is historical: it remains the
production database and must be retained.

## Migration services

The deployments for `ghost-validation` and the legacy `MySQL` service were
stopped using `railway down --service SERVICE_ID --yes`. Their services,
attached volumes and private migration backups were preserved for recovery.
Stopped volumes still incur storage charges. Do not delete or detach them as
part of routine cost reductions.

The previous memory snapshot attributed 672 MiB to these two containers. Actual
savings depend on average billed memory/CPU; a snapshot is not a billing forecast.

## Production MySQL

The database contained approximately 38 MiB of tables/indexes and had peaked at
12 connections since its previous startup. The memory settings recorded in
`infra/services.json` retain a 128 MiB InnoDB buffer pool, reduce the log buffer
to 16 MiB, allow 40 connections, and bound table caches and temporary-table RAM.
Performance Schema remains enabled. These are startup settings, not SQL writes
or a restrictive container RAM cap. They were validated with
`mysqld --validate-config` before requesting one redeployment.

The previous Railway startup-command override was empty (`null`). To revert,
clear that override in the live MySQL service settings, retain the existing
image and volume, and redeploy once. Do not change Ghost's database connection
or the project's external PostgreSQL URL.

## Billing alerts

The existing workspace compute email alert was $10 and the hard limit was $25.
Both were preserved. The hard limit can stop workloads when reached; it was
already configured, not introduced by this review. Check the workspace Usage
page when revising thresholds. A recent usage estimate is not a guaranteed bill.

The installed Railway CLI is older; an existing isolated CLI supporting usage
commands was reused without replacing the global installation. Current CLIs
support `railway usage --json` and `railway usage limit status`. Omitted values
in a limit update preserve existing thresholds.

Resource limits bound worst-case usage; they do not lower an unchanged idle
baseline. Review average usage and peaks before setting them. The email worker
was left unchanged because its observed idle footprint was small.
