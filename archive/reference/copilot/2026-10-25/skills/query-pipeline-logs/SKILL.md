---
name: query-pipeline-logs
description: "Query the PostgreSQL pipeline_logs table to inspect, debug, or summarise pipeline runs — both local and Railway email-triggered. Use when: checking whether a run succeeded or failed, finding the last published URL, investigating which stage errored, reviewing Railway email-triggered runs, counting posts published in a period, or any debugging question about a past pipeline execution."
argument-hint: "Optional: describe what you want to find (e.g. 'last 10 runs', 'failed runs this week', 'run for topic X', 'latest published URL')"
---

# Query Pipeline Logs

Queries the shared PostgreSQL `pipeline_logs` table. Every pipeline event — from both local CLI runs and Railway email-triggered runs — is written here, surviving Railway redeployments.

## Table Schema

```
pipeline_logs
  id         BIGSERIAL PRIMARY KEY
  run_id     TEXT          — 12-hex-char UUID prefix; groups all events for one run
  event      TEXT          — see Event Types below
  stage      TEXT          — null for run-level events; 'Research'|'Write'|'Edit'|'Publish'|'Index'|'LinkedIn' for stage events
  ts         TIMESTAMPTZ   — when the event was logged (UTC)
  data       JSONB         — full event payload (all fields below)
  created_at TIMESTAMPTZ   — DB insert time
```

### Event Types

| event | Description | Key `data` fields |
|---|---|---|
| `run_start` | Pipeline run begins | `command`, `topic`, `env` |
| `stage_start` | A stage begins | `stage` |
| `stage_ok` | Stage completed successfully | `stage`, `elapsed_s`, `model`, `draft`, `url` |
| `stage_error` | Stage failed | `stage`, `error_type`, `error_message`, `traceback`, `cause_chain` |
| `stage_skipped` | Stage intentionally skipped | `stage`, `reason` |
| `stage_warning` | Non-fatal warning during a stage | `stage`, `message` |
| `run_complete` | Full pipeline finished | `published_url`, `total_elapsed_s` |
| `run_failed` | Pipeline aborted | `failed_stage`, `error_type`, `error_message`, `traceback` |
| `model_fallback` | Model downgraded mid-run | `stage`, `agent`, `from_model`, `to_model`, `attempt`, `reason` |
| `email_received` | Email command accepted | `from`, `command`, `topic` |
| `email_ignored` | Email had no valid command | `from`, `subject`, `reason` |
| `email_rejected` | Email from non-allowlisted sender | `from`, `subject`, `reason` |
| `email_task_complete` | Email-triggered run finished | `command`, `topic`, `url` |
| `email_task_failed` | Email-triggered run failed | `command`, `topic`, `failed_stage` |

## Procedure

### Run the query script

```bash
source .venv/bin/activate
python scripts/query_logs.py [QUERY_NAME] [--run-id RUN_ID] [--days N] [--limit N]
```

| Query name | What it shows |
|---|---|
| `runs` (default) | Last N pipeline runs with status, topic, duration |
| `failures` | Recent failed runs with error details |
| `emails` | Email-triggered events (Railway runs) |
| `run` | Full event trace for a single `--run-id` |
| `stage` | Per-stage timing stats across all runs |
| `published` | Published URLs, newest first |

### Raw psql (connect directly to Railway)

Connection: `caboose.proxy.rlwy.net:21688`  
Database and credentials are in `.env` as `DATABASE_URL`.

```bash
# Start an interactive session
psql "$DATABASE_URL"
```

#### Useful queries

```sql
-- Last 20 runs (topic, command, duration, outcome)
SELECT
    l.run_id,
    l.data->>'command'     AS command,
    l.data->>'topic'       AS topic,
    l.ts                   AS started_at,
    c.data->>'total_elapsed_s' AS elapsed_s,
    CASE WHEN f.run_id IS NOT NULL THEN 'FAILED' ELSE 'OK' END AS status
FROM pipeline_logs l
LEFT JOIN pipeline_logs c ON c.run_id = l.run_id AND c.event = 'run_complete'
LEFT JOIN pipeline_logs f ON f.run_id = l.run_id AND f.event = 'run_failed'
WHERE l.event = 'run_start'
ORDER BY l.ts DESC
LIMIT 20;

-- Latest published URLs
SELECT data->>'published_url' AS url, ts
FROM pipeline_logs
WHERE event = 'run_complete'
  AND data->>'published_url' != ''
ORDER BY ts DESC
LIMIT 10;

-- All events for a specific run  (replace the run_id)
SELECT event, stage, ts, data
FROM pipeline_logs
WHERE run_id = 'abc123def456'
ORDER BY ts;

-- Recent stage errors (with error message)
SELECT run_id, stage, data->>'error_type' AS error_type,
       data->>'error_message' AS message, ts
FROM pipeline_logs
WHERE event = 'stage_error'
ORDER BY ts DESC
LIMIT 20;

-- Failed runs this week
SELECT run_id, data->>'failed_stage' AS failed_stage,
       data->>'error_type' AS error_type,
       data->>'error_message' AS message, ts
FROM pipeline_logs
WHERE event = 'run_failed'
  AND ts > NOW() - INTERVAL '7 days'
ORDER BY ts DESC;

-- Email-triggered runs on Railway
SELECT data->>'command' AS command, data->>'topic' AS topic,
       data->>'url' AS published_url, ts
FROM pipeline_logs
WHERE event = 'email_task_complete'
ORDER BY ts DESC
LIMIT 20;

-- Rejected / ignored emails
SELECT event, data->>'from' AS sender,
       data->>'subject' AS subject, data->>'reason' AS reason, ts
FROM pipeline_logs
WHERE event IN ('email_rejected', 'email_ignored')
ORDER BY ts DESC
LIMIT 20;

-- Average per-stage duration
SELECT stage,
       ROUND(AVG((data->>'elapsed_s')::numeric), 1) AS avg_s,
       COUNT(*) AS runs
FROM pipeline_logs
WHERE event = 'stage_ok'
GROUP BY stage
ORDER BY avg_s DESC;

-- Model fallbacks (rate-limit events)
SELECT stage, data->>'agent' AS agent,
       data->>'from_model' AS from_model,
       data->>'to_model'   AS to_model,
       data->>'reason'     AS reason, ts
FROM pipeline_logs
WHERE event = 'model_fallback'
ORDER BY ts DESC
LIMIT 20;

-- Posts published per day (last 30 days)
SELECT DATE(ts) AS day, COUNT(*) AS posts
FROM pipeline_logs
WHERE event = 'run_complete'
  AND data->>'published_url' != ''
  AND ts > NOW() - INTERVAL '30 days'
GROUP BY DATE(ts)
ORDER BY day DESC;
```

## Notes

- Logs from Railway email-triggered runs appear here automatically — no SSH or Railway CLI needed.
- The file-based log (`logs/pipeline-YYYY-MM-DD.log`) still exists locally as a secondary fallback.
- `run_id` is a 12-character hex prefix — use it to correlate all events for one pipeline execution.
- All times are UTC (`TIMESTAMPTZ`). Convert to local if needed: `ts AT TIME ZONE 'Europe/London'`.
