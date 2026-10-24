"""Quick script to check rate_limit_log table schema."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def load_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value and key not in os.environ:
                    os.environ[key] = value


async def main():
    import asyncpg

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    async with pool.acquire() as conn:
        cols = await conn.fetch(
            "SELECT column_name, data_type, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = 'rate_limit_log' "
            "ORDER BY ordinal_position"
        )
        if cols:
            print("rate_limit_log columns:")
            for c in cols:
                print(f"  {c['column_name']:20s} {c['data_type']:20s} default={c['column_default']}")
        else:
            print("Table rate_limit_log does NOT exist")
            await pool.close()
            return

        row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM rate_limit_log")
        print(f"\nTotal rows: {row['cnt']}")

        # Show a sample row if any exist
        sample = await conn.fetchrow("SELECT * FROM rate_limit_log ORDER BY id DESC LIMIT 1")
        if sample:
            print("\nLatest row:")
            for key, val in sample.items():
                print(f"  {key}: {val}")
    await pool.close()


if __name__ == "__main__":
    load_env()
    asyncio.run(main())
