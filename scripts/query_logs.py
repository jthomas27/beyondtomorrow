"""scripts/query_logs.py — Query the pipeline_logs PostgreSQL table.

Queries both local and Railway email-triggered run history.

Usage:
    python scripts/query_logs.py [runs|failures|emails|run|stage|published|stale]
                                 [--run-id RUN_ID] [--days N] [--limit N]

Queries:
    runs       (default) Last N pipeline runs with status, topic, duration, LinkedIn status
    failures   Recent failed runs with error details
    emails     Email-triggered events (Railway runs)
    run        Full event trace for a single --run-id
    stage      Per-stage average timing across all runs
    published  Published Ghost post URLs, newest first
    stale      Runs auto-closed by the stale-run janitor (killed without a terminal event)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `pipeline` is importable whether
# this script is run as `python scripts/query_logs.py` or `python -m scripts.query_logs`.
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _load_dotenv() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.is_file():
        return
    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v


_load_dotenv()


async def main(argv: list[str] | None = None) -> None:
    from pipeline.db import get_pool, close_pool

    parser = argparse.ArgumentParser(
        description="Query the pipeline_logs PostgreSQL table.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="runs",
        choices=["runs", "failures", "emails", "run", "stage", "published", "stale"],
        help="Query to run (default: runs)",
    )
    parser.add_argument("--run-id", default=None, help="12-char run_id for the 'run' query")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days (default: 30)")
    parser.add_argument("--limit", type=int, default=20, help="Max rows to return (default: 20)")
    args = parser.parse_args(argv)

    pool = await get_pool()

    async with pool.acquire() as conn:
        if args.query == "run":
            if not args.run_id:
                print("Error: --run-id is required for the 'run' query", file=sys.stderr)
                await close_pool()
                sys.exit(1)
            rows = await conn.fetch(
                """
                SELECT event, stage, ts, data
                FROM pipeline_logs
                WHERE run_id = $1
                ORDER BY ts
                """,
                args.run_id,
            )
            if not rows:
                print(f"No events found for run_id '{args.run_id}'")
            for r in rows:
                stage_label = f"  stage={r['stage']}" if r['stage'] else ""
                print(f"{r['ts'].strftime('%H:%M:%S.%f')[:12]}  {r['event']:22s}{stage_label}")
                # Print key data fields inline
                raw = r['data'] or '{}'
                import json as _json
                data = _json.loads(raw) if isinstance(raw, str) else (raw or {})
                for key in ('topic', 'command', 'error_type', 'error_message', 'published_url',
                            'total_elapsed_s', 'elapsed_s', 'model', 'reason', 'failed_stage'):
                    if key in data and data[key]:
                        print(f"                         {key}={data[key]}")

        elif args.query == "failures":
            rows = await conn.fetch(
                """
                SELECT run_id,
                       data->>'failed_stage'   AS failed_stage,
                       data->>'error_type'     AS error_type,
                       data->>'error_message'  AS error_message,
                       ts
                FROM pipeline_logs
                WHERE event = 'run_failed'
                  AND ts > NOW() - ($1 || ' days')::INTERVAL
                ORDER BY ts DESC
                LIMIT $2
                """,
                str(args.days), args.limit,
            )
            if not rows:
                print(f"No failures in the last {args.days} days.")
            for r in rows:
                print(
                    f"{r['ts'].date()}  {r['run_id']}  "
                    f"stage={r['failed_stage'] or '?'}  "
                    f"{r['error_type'] or ''}: {r['error_message'] or ''}"
                )

        elif args.query == "emails":
            rows = await conn.fetch(
                """
                SELECT event,
                       data->>'command'  AS command,
                       data->>'topic'    AS topic,
                       data->>'url'      AS url,
                       data->>'from'     AS sender,
                       data->>'reason'   AS reason,
                       ts
                FROM pipeline_logs
                WHERE event LIKE 'email_%'
                  AND ts > NOW() - ($1 || ' days')::INTERVAL
                ORDER BY ts DESC
                LIMIT $2
                """,
                str(args.days), args.limit,
            )
            if not rows:
                print(f"No email events in the last {args.days} days.")
            for r in rows:
                detail = r['topic'] or r['url'] or r['reason'] or ""
                cmd = r['command'] or ""
                print(
                    f"{r['ts'].strftime('%Y-%m-%d %H:%M')}  "
                    f"{r['event']:25s}  "
                    f"{cmd:8s}  "
                    f"{detail}"
                )

        elif args.query == "published":
            rows = await conn.fetch(
                """
                SELECT data->>'published_url' AS url, ts
                FROM pipeline_logs
                WHERE event = 'run_complete'
                  AND data->>'published_url' != ''
                  AND ts > NOW() - ($1 || ' days')::INTERVAL
                ORDER BY ts DESC
                LIMIT $2
                """,
                str(args.days), args.limit,
            )
            if not rows:
                print(f"No published posts in the last {args.days} days.")
            for r in rows:
                print(f"{r['ts'].date()}  {r['url']}")

        elif args.query == "stage":
            rows = await conn.fetch(
                """
                SELECT stage,
                       ROUND(AVG((data->>'elapsed_s')::numeric), 1) AS avg_s,
                       ROUND(MIN((data->>'elapsed_s')::numeric), 1) AS min_s,
                       ROUND(MAX((data->>'elapsed_s')::numeric), 1) AS max_s,
                       COUNT(*) AS runs
                FROM pipeline_logs
                WHERE event = 'stage_ok'
                  AND ts > NOW() - ($1 || ' days')::INTERVAL
                GROUP BY stage
                ORDER BY avg_s DESC
                """,
                str(args.days),
            )
            if not rows:
                print(f"No stage data in the last {args.days} days.")
            else:
                print(f"{'Stage':12s}  {'Avg':>7s}  {'Min':>7s}  {'Max':>7s}  {'Runs':>5s}")
                print("-" * 45)
                for r in rows:
                    print(
                        f"{r['stage']:12s}  "
                        f"{str(r['avg_s']) + 's':>7s}  "
                        f"{str(r['min_s']) + 's':>7s}  "
                        f"{str(r['max_s']) + 's':>7s}  "
                        f"{r['runs']:>5d}"
                    )

        elif args.query == "stale":
            rows = await conn.fetch(
                """
                SELECT run_id,
                       data->>'failed_stage'    AS last_stage,
                       data->>'total_elapsed_s' AS elapsed,
                       ts
                FROM pipeline_logs
                WHERE event = 'run_failed'
                  AND data->>'stale_cleanup' = 'true'
                  AND ts > NOW() - ($1 || ' days')::INTERVAL
                ORDER BY ts DESC
                LIMIT $2
                """,
                str(args.days), args.limit,
            )
            if not rows:
                print(f"No stale-cleaned runs in the last {args.days} days.")
            else:
                print(f"{'Cleaned At':16s}  {'Run ID':12s}  {'Last Stage':12s}  {'Elapsed':10s}")
                print("-" * 60)
                for r in rows:
                    elapsed = f"{r['elapsed']}s" if r['elapsed'] else "?"
                    print(
                        f"{r['ts'].strftime('%Y-%m-%d %H:%M')}  "
                        f"{r['run_id']:12s}  "
                        f"{(r['last_stage'] or '?'):12s}  "
                        f"{elapsed}"
                    )

        else:  # runs (default)
            rows = await conn.fetch(
                """
                SELECT
                    l.run_id,
                    l.data->>'command'            AS command,
                    l.data->>'topic'              AS topic,
                    l.ts                          AS started_at,
                    c.data->>'total_elapsed_s'    AS elapsed,
                    p.data->>'published_url'      AS published_url,
                    c.data->>'linkedin_ok'        AS linkedin_ok,
                    c.data->>'linkedin_skipped'   AS linkedin_skipped,
                    CASE
                        WHEN f.run_id IS NOT NULL THEN 'FAILED'
                        WHEN c.run_id IS NOT NULL THEN 'OK'
                        ELSE 'RUNNING'
                    END AS status
                FROM pipeline_logs l
                LEFT JOIN pipeline_logs c
                    ON c.run_id = l.run_id AND c.event = 'run_complete'
                LEFT JOIN pipeline_logs p
                    ON p.run_id = l.run_id AND p.event = 'run_complete'
                LEFT JOIN pipeline_logs f
                    ON f.run_id = l.run_id AND f.event = 'run_failed'
                WHERE l.event = 'run_start'
                  AND l.ts > NOW() - ($1 || ' days')::INTERVAL
                ORDER BY l.ts DESC
                LIMIT $2
                """,
                str(args.days), args.limit,
            )
            if not rows:
                print(f"No pipeline runs in the last {args.days} days.")
            else:
                print(
                    f"{'Date':10s}  {'Run ID':12s}  {'Status':7s}  "
                    f"{'Cmd':8s}  {'Elapsed':8s}  {'LinkedIn':12s}  Topic"
                )
                print("-" * 100)
                for r in rows:
                    elapsed = f"{r['elapsed']}s" if r['elapsed'] else "?"
                    topic = (r['topic'] or "")[:50]
                    li_raw = r['linkedin_ok']
                    li_skip = r['linkedin_skipped']
                    if r['status'] != 'OK':
                        li_col = "-"
                    elif li_skip == 'true':
                        li_col = "skipped"
                    elif li_raw == 'true':
                        li_col = "posted"
                    elif li_raw == 'false':
                        li_col = "FAILED"
                    else:
                        li_col = "?"  # pre-feature run or unknown
                    print(
                        f"{r['started_at'].date()}  "
                        f"{r['run_id']:12s}  "
                        f"{r['status']:7s}  "
                        f"{(r['command'] or ''):8s}  "
                        f"{elapsed:8s}  "
                        f"{li_col:12s}  "
                        f"{topic}"
                    )

    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
