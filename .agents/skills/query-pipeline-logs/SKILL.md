---
name: query-pipeline-logs
description: "Read recent pipeline runs, failures, stage timings and published URLs without replaying tasks or publishing content."
---

Run commands from the repository root using `.venv/bin/python`. Follow `AGENTS.md`; reuse established task authorisation and service access.

# Query pipeline history

Use the existing read-only query command; this does not require Railway SSH:

```bash
.venv/bin/python scripts/query_logs.py runs --limit 10
.venv/bin/python scripts/query_logs.py failures --days 7 --limit 10
.venv/bin/python scripts/query_logs.py published --limit 5
.venv/bin/python scripts/query_logs.py run --run-id RUN_ID
```

Other query modes are `emails` and `stage`. Select the smallest window and mode
that answers the question. `run_id` groups events from one pipeline execution.
Times are UTC. A published URL and a completed run are different facts: inspect
later stage failures when the user asks whether the whole run succeeded.

For uncommon event/schema questions, read [the query reference](references/queries.md).
Summarise timestamps, outcome and relevant URLs. Redact credentials and personal
email content from diagnostics. Do not rerun a failed command or send a notification
merely because the user asked to inspect logs.
