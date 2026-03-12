"""
tests/test_embeddings.py — Unit and integration tests for pipeline/embeddings.py

Unit tests (no DB required):
    - embed() returns a correct-dimensional, L2-normalised vector
    - embed_batch() is consistent with individual embed() calls
    - similarity() ranks semantically related pairs above unrelated ones
    - get_model_info() returns the expected metadata dict

Integration tests (require DATABASE_URL env var — mark with -m integration):
    - HNSW index exists on embeddings.embedding column in PostgreSQL
    - Query planner uses the index for ANN searches (EXPLAIN output)

Run unit tests only:
    pytest tests/test_embeddings.py -m "not integration"

Run all including DB integration:
    DATABASE_URL=<url> pytest tests/test_embeddings.py
"""

import os
import math
import pytest
import pytest_asyncio

from pipeline.embeddings import embed, embed_batch, similarity, get_model_info

# ---------------------------------------------------------------------------
# Unit tests — local model, no network or DB needed
# ---------------------------------------------------------------------------

def test_embed_returns_384_dimensions():
    """embed() must return exactly 384 floats for all-MiniLM-L6-v2."""
    vec = embed("Climate change is accelerating ice sheet loss.")
    assert isinstance(vec, list)
    assert len(vec) == 384
    assert all(isinstance(v, float) for v in vec)


def test_embed_vector_is_unit_normalised():
    """MiniLM produces L2-normalised vectors; magnitude should be ~1.0."""
    vec = embed("Post-quantum cryptography standards are being finalised.")
    magnitude = math.sqrt(sum(v ** 2 for v in vec))
    assert abs(magnitude - 1.0) < 1e-4, f"Expected unit vector, got magnitude {magnitude:.6f}"


def test_embed_batch_count_matches_input():
    """embed_batch() must return one vector per input text."""
    texts = [
        "Renewable energy capacity doubled last year.",
        "Ocean acidification threatens coral reef ecosystems.",
        "Large language models are transforming scientific research.",
    ]
    vectors = embed_batch(texts)
    assert len(vectors) == len(texts)
    for vec in vectors:
        assert len(vec) == 384


def test_embed_batch_empty_input_returns_empty_list():
    """embed_batch([]) must return [] without error."""
    result = embed_batch([])
    assert result == []


def test_embed_batch_consistent_with_individual_embed():
    """A single-item batch should produce the same vector as embed()."""
    text = "Biodiversity loss is a crisis equal to climate change."
    single = embed(text)
    batch = embed_batch([text])
    assert len(batch) == 1
    # Cosine similarity between batch[0] and single should be ~1.0
    sim = similarity(single, batch[0])
    assert sim > 0.9999, f"Inconsistent embedding: similarity={sim}"


def test_similarity_related_texts_rank_above_unrelated():
    """Semantically related texts should score higher than unrelated ones."""
    texts = [
        "Global temperatures are rising due to greenhouse gases.",   # index 0
        "Carbon emissions from fossil fuels drive climate warming.", # index 1 (related)
        "The latest football World Cup results were surprising.",    # index 2 (unrelated)
    ]
    vecs = embed_batch(texts)
    sim_related = similarity(vecs[0], vecs[1])
    sim_unrelated = similarity(vecs[0], vecs[2])
    assert sim_related > sim_unrelated, (
        f"Related similarity ({sim_related:.4f}) should exceed "
        f"unrelated ({sim_unrelated:.4f})"
    )


def test_similarity_identical_text_is_near_one():
    """Cosine similarity of a vector with itself must be effectively 1.0."""
    vec = embed("Fusion energy could solve the global energy crisis.")
    sim = similarity(vec, vec)
    assert sim > 0.9999, f"Self-similarity should be ~1.0, got {sim}"


def test_get_model_info_returns_correct_metadata():
    """get_model_info() must report the correct model and dimension."""
    info = get_model_info()
    assert info["model"] == "all-MiniLM-L6-v2"
    assert info["dimensions"] == 384
    assert info["cost_per_call"] == 0.0
    assert isinstance(info["loaded"], bool)


# ---------------------------------------------------------------------------
# Integration tests — require a live PostgreSQL + pgvector DB
# Skip unless DATABASE_URL is set and -m integration is passed
# ---------------------------------------------------------------------------

pytestmark_integration = pytest.mark.integration


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hnsw_index_exists_on_embeddings_column():
    """
    INTEGRATION: verify an HNSW index exists on embeddings.embedding.

    If this test fails, create the index with:

        CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw
        ON embeddings
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);

    Then VACUUM ANALYZE embeddings; to update planner statistics.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — skipping DB integration test")

    import asyncpg

    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'embeddings'
              AND indexdef ILIKE '%hnsw%'
            """
        )
    finally:
        await conn.close()

    assert rows, (
        "No HNSW index found on the 'embeddings' table.\n"
        "Create one with:\n\n"
        "  CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw\n"
        "  ON embeddings\n"
        "  USING hnsw (embedding vector_cosine_ops)\n"
        "  WITH (m = 16, ef_construction = 64);\n\n"
        "  VACUUM ANALYZE embeddings;\n"
    )

    index_name = rows[0]["indexname"]
    index_def = rows[0]["indexdef"]
    assert "hnsw" in index_def.lower(), f"Unexpected index definition: {index_def}"
    print(f"\n✓ HNSW index found: {index_name}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hnsw_index_used_by_query_planner():
    """
    INTEGRATION: verify the query planner uses the HNSW index for ANN searches.

    Checks that EXPLAIN output contains 'Index Scan' for a cosine-distance
    ORDER BY query, confirming the index is active and being used.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — skipping DB integration test")

    import asyncpg

    # Build a dummy query vector (384 zeros — just to test the planner)
    dummy_vector = "[" + ",".join(["0"] * 384) + "]"

    conn = await asyncpg.connect(database_url)
    try:
        # Register the vector codec so asyncpg can handle the type
        await conn.set_type_codec(
            "vector",
            encoder=lambda v: v,
            decoder=lambda v: v,
            schema="public",
            format="text",
        )
        explain_rows = await conn.fetch(
            f"""
            EXPLAIN (FORMAT TEXT)
            SELECT id, content
            FROM embeddings
            ORDER BY embedding <=> '{dummy_vector}'::vector
            LIMIT 5
            """
        )
    finally:
        await conn.close()

    explain_text = "\n".join(r[0] for r in explain_rows)
    print(f"\nQuery plan:\n{explain_text}")

    assert "Index Scan" in explain_text or "Bitmap Index Scan" in explain_text, (
        "Query planner is NOT using the HNSW index for cosine ANN search.\n"
        "Possible causes:\n"
        "  1. The index does not exist yet (run test_hnsw_index_exists first)\n"
        "  2. Table is too small for the planner to prefer index over seq scan\n"
        "     (add more rows or SET enable_seqscan = off for testing)\n"
        f"Full plan:\n{explain_text}"
    )
