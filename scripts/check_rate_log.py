"""Check recent rate_limit_log entries."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scripts.check_db_schema import load_env

load_env()


async def main():
    import asyncpg
    from datetime import date

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, agent_name, model, tokens_input, tokens_output, "
            "request_type, created_at "
            "FROM rate_limit_log ORDER BY id DESC LIMIT 15"
        )
        print("Last 15 log entries:")
        for r in rows:
            m = (r["model"] or "?").replace("openai/", "")
            ts = str(r["created_at"])[:19]
            print(
                f"  #{r['id']:>3}  {r['agent_name']:<14} {m:<16} "
                f"in={r['tokens_input']:<6} out={r['tokens_output']:<6} "
                f"type={r['request_type']:<14} {ts}"
            )

        today = date.today()
        usage = await conn.fetch(
            "SELECT model, COUNT(*) as cnt FROM rate_limit_log "
            "WHERE created_at::date = $1 GROUP BY model ORDER BY cnt DESC",
            today,
        )
        print(f"\nToday ({today}) usage by model:")
        for u in usage:
            print(f"  {u['model']}: {u['cnt']} calls")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
