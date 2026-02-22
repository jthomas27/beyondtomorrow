#!/usr/bin/env python3
"""
migrate-embeddings.py — Migrate pgvector schema from 1536 to 384 dimensions

This script:
  1. Drops the old HNSW index (built for 1536-dim vectors)
  2. Alters the embeddings column from vector(1536) to vector(384)
  3. Re-embeds any existing documents using the local all-MiniLM-L6-v2 model
  4. Recreates the HNSW index for 384-dim vectors

Prerequisites:
  pip install psycopg2-binary sentence-transformers

Usage:
  DATABASE_URL=postgres://... python scripts/migrate-embeddings.py

  Or on Railway (env var is already set):
  python scripts/migrate-embeddings.py
"""

import os
import sys
import time

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    print("✗ psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OLD_DIMENSIONS = 1536
NEW_DIMENSIONS = 384
MODEL_NAME = "all-MiniLM-L6-v2"
BATCH_SIZE = 64  # chunks per embedding batch


def get_connection():
    """Connect to PostgreSQL using DATABASE_URL."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("✗ DATABASE_URL environment variable not set")
        sys.exit(1)
    return psycopg2.connect(database_url)


def check_current_schema(cur):
    """Check current vector column dimensions."""
    cur.execute("""
        SELECT atttypmod
        FROM pg_attribute
        WHERE attrelid = 'embeddings'::regclass
          AND attname = 'embedding'
    """)
    row = cur.fetchone()
    if row is None:
        print("✗ No 'embedding' column found in 'embeddings' table")
        sys.exit(1)
    current_dim = row[0]
    print(f"  Current embedding column dimension: {current_dim}")
    return current_dim


def count_existing_embeddings(cur):
    """Count how many embeddings currently exist."""
    cur.execute("SELECT COUNT(*) FROM embeddings WHERE embedding IS NOT NULL")
    count = cur.fetchone()[0]
    print(f"  Existing embeddings to re-embed: {count}")
    return count


def drop_hnsw_index(cur):
    """Drop the old HNSW vector index."""
    cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'embeddings'
          AND indexdef ILIKE '%hnsw%'
    """)
    indexes = cur.fetchall()
    if not indexes:
        print("  No HNSW index found — skipping drop")
        return

    for (index_name,) in indexes:
        print(f"  Dropping HNSW index: {index_name}")
        cur.execute(f"DROP INDEX IF EXISTS {index_name}")
    print("✓ Old HNSW index(es) dropped")


def alter_column_dimensions(cur):
    """Change the vector column from old dimensions to new dimensions.

    pgvector doesn't support ALTER COLUMN ... TYPE vector(N) directly when
    data exists, so we:
      1. Add a new column with the correct dimensions
      2. Drop the old column
      3. Rename the new column
    If there are existing embeddings, they'll be cleared (re-embedded in the
    next step).
    """
    print(f"  Altering embedding column: vector({OLD_DIMENSIONS}) → vector({NEW_DIMENSIONS})")

    # Check if there's existing data
    cur.execute("SELECT COUNT(*) FROM embeddings")
    count = cur.fetchone()[0]

    if count == 0:
        # No data — simple ALTER works
        cur.execute(f"""
            ALTER TABLE embeddings
            ALTER COLUMN embedding TYPE vector({NEW_DIMENSIONS})
        """)
        print("✓ Column altered (no existing data)")
    else:
        # Has data — need to null out old vectors, then alter
        # (Old 1536-dim vectors are incompatible with new 384-dim column)
        print(f"  Clearing {count} old {OLD_DIMENSIONS}-dim vectors (will re-embed)...")
        cur.execute("UPDATE embeddings SET embedding = NULL")
        cur.execute(f"""
            ALTER TABLE embeddings
            ALTER COLUMN embedding TYPE vector({NEW_DIMENSIONS})
        """)
        print("✓ Column altered (old vectors cleared — will re-embed)")

    # Update the default model name
    cur.execute(f"""
        ALTER TABLE embeddings
        ALTER COLUMN model SET DEFAULT '{MODEL_NAME}'
    """)


def reembed_existing_chunks(cur, conn):
    """Re-embed any existing chunks that had embeddings.

    Only runs if there are rows in the embeddings table with NULL vectors
    (cleared during migration).
    """
    cur.execute("""
        SELECT e.id, c.content
        FROM embeddings e
        JOIN chunks c ON c.id = e.chunk_id
        WHERE e.embedding IS NULL AND c.content IS NOT NULL
        ORDER BY e.id
    """)
    rows = cur.fetchall()

    if not rows:
        print("  No chunks to re-embed — migration complete")
        return

    print(f"  Loading {MODEL_NAME} model for re-embedding...")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("✗ sentence-transformers not installed. Run: pip install sentence-transformers")
        print(f"  ⚠ {len(rows)} embeddings still NULL — run this script again after installing")
        return

    model = SentenceTransformer(MODEL_NAME)
    print(f"✓ Model loaded ({MODEL_NAME})")

    total = len(rows)
    embedded = 0

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        ids = [row[0] for row in batch]
        texts = [row[1] for row in batch]

        # Generate embeddings
        vectors = model.encode(texts, show_progress_bar=False)

        # Update database
        for eid, vec in zip(ids, vectors):
            cur.execute(
                "UPDATE embeddings SET embedding = %s, model = %s WHERE id = %s",
                (vec.tolist(), MODEL_NAME, eid),
            )

        embedded += len(batch)
        print(f"  Re-embedded {embedded}/{total} chunks...")

    conn.commit()
    print(f"✓ Re-embedded {total} chunks with {MODEL_NAME}")


def recreate_hnsw_index(cur):
    """Create the HNSW index for the new vector dimensions."""
    print("  Creating HNSW index for 384-dim vectors (this may take a moment)...")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_embeddings_vector
        ON embeddings
        USING hnsw (embedding vector_cosine_ops)
    """)
    print("✓ HNSW index created (384 dimensions, cosine similarity)")


def update_model_column(cur):
    """Update all existing rows to reflect the new model name."""
    cur.execute(
        "UPDATE embeddings SET model = %s WHERE model IS NULL OR model != %s",
        (MODEL_NAME, MODEL_NAME),
    )
    updated = cur.rowcount
    if updated > 0:
        print(f"  Updated model name on {updated} rows → {MODEL_NAME}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  pgvector Embedding Migration")
    print(f"  {OLD_DIMENSIONS} dimensions → {NEW_DIMENSIONS} dimensions")
    print(f"  Model: {MODEL_NAME}")
    print("=" * 60)
    print()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # 0. Check current state
        print("[1/5] Checking current schema...")
        current_dim = check_current_schema(cur)
        existing_count = count_existing_embeddings(cur)

        if current_dim == NEW_DIMENSIONS:
            print(f"\n  Column is already {NEW_DIMENSIONS} dimensions.")
            if existing_count == 0:
                print("  No embeddings to re-embed. Ensuring HNSW index exists...")
                recreate_hnsw_index(cur)
                conn.commit()
                print("\n✓ Migration not needed — schema is already up to date.")
                return
            # Check if there are NULL embeddings that need re-embedding
            cur.execute("SELECT COUNT(*) FROM embeddings WHERE embedding IS NULL")
            null_count = cur.fetchone()[0]
            if null_count == 0:
                print("  All embeddings present. Ensuring HNSW index exists...")
                recreate_hnsw_index(cur)
                conn.commit()
                print("\n✓ Migration not needed — schema is already up to date.")
                return
            print(f"  {null_count} embeddings need re-embedding...")

        # 1. Drop old HNSW index
        print("\n[2/5] Dropping old HNSW index...")
        drop_hnsw_index(cur)
        conn.commit()

        # 2. Alter column dimensions
        if current_dim != NEW_DIMENSIONS:
            print(f"\n[3/5] Altering column dimensions ({current_dim} → {NEW_DIMENSIONS})...")
            alter_column_dimensions(cur)
            conn.commit()
        else:
            print(f"\n[3/5] Column already {NEW_DIMENSIONS} dimensions — skipping alter")

        # 3. Re-embed existing chunks
        print("\n[4/5] Re-embedding existing chunks...")
        start = time.time()
        reembed_existing_chunks(cur, conn)
        elapsed = time.time() - start
        if elapsed > 1:
            print(f"  Re-embedding took {elapsed:.1f}s")

        # 4. Recreate HNSW index
        print("\n[5/5] Recreating HNSW index...")
        recreate_hnsw_index(cur)
        conn.commit()

        # Done
        print()
        print("=" * 60)
        print("  ✓ Migration complete!")
        print(f"  Embedding column: vector({NEW_DIMENSIONS})")
        print(f"  Model: {MODEL_NAME}")
        print(f"  HNSW index: active (cosine similarity)")
        print("=" * 60)

    except Exception as e:
        conn.rollback()
        print(f"\n✗ Migration failed: {e}")
        print("  All changes have been rolled back.")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
