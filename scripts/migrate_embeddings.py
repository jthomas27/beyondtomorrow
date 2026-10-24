#!/usr/bin/env python3
"""
migrate_embeddings.py — Re-chunk and re-embed all documents with the new model.

Reads every document from the `documents` table, re-chunks with the current
config (350 words / 35 overlap for bge-small-en-v1.5), generates fresh
embeddings, and replaces the old chunks + embeddings.

Run once after switching the embedding model. Safe to re-run (idempotent).

Usage:
    source .venv/bin/activate
    .venv/bin/python scripts/migrate_embeddings.py [--dry-run] [--batch-size N]
"""

import argparse
import asyncio
import json
import os
import sys
import time

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from pipeline.db import get_pool, close_pool
from pipeline.embeddings import embed_batch, get_model_info
from pipeline.tools.corpus import _chunk_text, _get_chunk_params


async def migrate(dry_run: bool = False, batch_size: int = 10) -> None:
    model_info = get_model_info()
    max_w, overlap_w = _get_chunk_params()

    print(f"Migration settings:")
    print(f"  Model:         {model_info['model']}")
    print(f"  Dimensions:    {model_info['dimensions']}")
    print(f"  Chunk size:    {max_w} words, {overlap_w} overlap")
    print(f"  Dry run:       {dry_run}")
    print()

    pool = await get_pool()

    # Fetch all documents
    async with pool.acquire() as conn:
        docs = await conn.fetch(
            "SELECT id, source, source_type, content FROM documents ORDER BY id"
        )

    total = len(docs)
    print(f"Found {total} documents to re-embed.\n")

    if total == 0:
        print("Nothing to do.")
        return

    migrated = 0
    skipped = 0
    total_chunks = 0
    start = time.monotonic()

    for i in range(0, total, batch_size):
        batch = docs[i : i + batch_size]
        for doc in batch:
            doc_id = doc["id"]
            source = doc["source"]
            content = doc["content"] or ""

            if not content.strip():
                print(f"  [{doc_id}] SKIP (empty): {source}")
                skipped += 1
                continue

            # Re-chunk
            chunks = _chunk_text(content, max_words=max_w, overlap_words=overlap_w)
            if not chunks:
                print(f"  [{doc_id}] SKIP (no chunks): {source}")
                skipped += 1
                continue

            if dry_run:
                print(f"  [{doc_id}] DRY RUN: {source} → {len(chunks)} chunks")
                total_chunks += len(chunks)
                migrated += 1
                continue

            # Embed
            vectors = embed_batch(chunks)
            doc_type = doc["source_type"] or "unknown"
            metadata = json.dumps({"source": source, "type": doc_type})

            # Replace in a single transaction
            async with pool.acquire() as conn:
                async with conn.transaction():
                    # Delete old chunks (cascades to embeddings)
                    old_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM chunks WHERE document_id = $1", doc_id
                    ) or 0
                    await conn.execute(
                        "DELETE FROM chunks WHERE document_id = $1", doc_id
                    )

                    # Batch insert new chunks
                    chunk_ids = await conn.fetch(
                        """
                        INSERT INTO chunks (document_id, chunk_index, content)
                        SELECT $1, unnest($2::int[]), unnest($3::text[])
                        RETURNING id
                        """,
                        doc_id,
                        list(range(len(chunks))),
                        chunks,
                    )

                    # Batch insert embeddings
                    await conn.executemany(
                        """
                        INSERT INTO embeddings (chunk_id, content, embedding, metadata)
                        VALUES ($1, $2, $3::vector, $4)
                        """,
                        [
                            (row["id"], chunk, vector, metadata)
                            for row, chunk, vector in zip(chunk_ids, chunks, vectors)
                        ],
                    )

            total_chunks += len(chunks)
            migrated += 1
            print(f"  [{doc_id}] OK: {source} — {old_count} → {len(chunks)} chunks")

        # Progress
        done = min(i + batch_size, total)
        elapsed = time.monotonic() - start
        print(f"\n  Progress: {done}/{total} documents ({elapsed:.1f}s elapsed)\n")

    elapsed = time.monotonic() - start
    print(f"\nMigration complete in {elapsed:.1f}s.")
    print(f"  Documents processed: {migrated}")
    print(f"  Documents skipped:   {skipped}")
    print(f"  Total chunks stored: {total_chunks}")

    await close_pool()


def main():
    parser = argparse.ArgumentParser(description="Re-embed all documents with the new model.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without writing.")
    parser.add_argument("--batch-size", type=int, default=10, help="Documents per progress batch.")
    args = parser.parse_args()

    asyncio.run(migrate(dry_run=args.dry_run, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
