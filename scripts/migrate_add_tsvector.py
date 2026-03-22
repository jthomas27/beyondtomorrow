"""
scripts/migrate_add_tsvector.py — One-time migration to add tsvector column + GIN index.

Adds a generated tsvector column (`ts`) to the `embeddings` table so that
`search_corpus()` can run hybrid semantic + full-text search via RRF.

Safe to re-run: skips if the column already exists.

Usage:
    .venv/bin/python scripts/migrate_add_tsvector.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
import asyncpg

load_dotenv()


async def main() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set.", file=sys.stderr)
        sys.exit(1)

    conn = await asyncpg.connect(db_url)
    try:
        # Check if column already exists
        exists = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'embeddings' AND column_name = 'ts'
            )
            """
        )
        if exists:
            print("ts column already exists — nothing to do.")
            return

        print("Adding generated tsvector column to embeddings…")
        await conn.execute(
            """
            ALTER TABLE embeddings
            ADD COLUMN ts tsvector
                GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
            """
        )
        print("  ✓  ts column added.")

        print("Creating GIN index on ts column…")
        await conn.execute(
            "CREATE INDEX embeddings_ts_idx ON embeddings USING GIN(ts)"
        )
        print("  ✓  GIN index created.")
        print("Migration complete.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
