"""
pipeline/tools/corpus.py — pgvector knowledge corpus tools

Normalized schema (documents → chunks → embeddings):

    documents
        id SERIAL PRIMARY KEY
        source VARCHAR(500) UNIQUE NOT NULL   — dedup key
        source_type VARCHAR(100)
        title VARCHAR(500)
        content TEXT                           — full original text
        created_at / updated_at TIMESTAMPTZ

    chunks
        id SERIAL PRIMARY KEY
        document_id INTEGER → documents(id) ON DELETE CASCADE
        chunk_index INTEGER
        content TEXT
        created_at TIMESTAMPTZ

    embeddings
        id SERIAL PRIMARY KEY
        chunk_id INTEGER → chunks(id) ON DELETE CASCADE
        content TEXT NOT NULL                  — denormalized for fast search (no join)
        embedding vector(384)
        metadata JSONB DEFAULT '{}'
        model VARCHAR(100) DEFAULT 'all-MiniLM-L6-v2'
        created_at TIMESTAMPTZ

Tools:
    search_corpus(query, top_k)                     — semantic similarity search
    index_document(content, source, doc_type, date) — chunk → embed → store (normalized)
    embed_and_store(text, source, metadata_json)    — embed a single pre-chunked text
"""

import json
import logging
import re as _re
from datetime import date as _date
from pipeline._sdk import function_tool
from pipeline.embeddings import embed, embed_batch
from pipeline.db import get_pool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cached config — loaded once per process, not on every tool call
# ---------------------------------------------------------------------------

_cached_limits: dict | None = None


def _get_limits() -> dict:
    """Return the limits config, caching after first load."""
    global _cached_limits
    if _cached_limits is None:
        try:
            from pipeline.config_loader import get_limits
            _cached_limits = get_limits()
        except Exception:
            _cached_limits = {}
    return _cached_limits


def _get_chunk_params() -> tuple[int, int]:
    """Return (max_words, overlap_words) from config."""
    limits = _get_limits()
    chunking = limits.get("chunking", {})
    return (
        chunking.get("max_words_per_chunk", 200),
        chunking.get("overlap_words", 30),
    )


@function_tool
async def search_corpus(query: str, top_k: int = 5) -> str:
    """Search the private knowledge corpus using hybrid semantic + full-text search.

    When the `ts` tsvector column is present (post-migration), combines pgvector
    cosine similarity with PostgreSQL full-text search and merges results via
    Reciprocal Rank Fusion (RRF).  Falls back to vector-only search if the column
    has not been migrated yet.

    Args:
        query: The search query — will be embedded and matched against stored documents.
        top_k: Number of results to return (default 5).
    """
    query_vector = embed(query)

    limits = _get_limits()
    corpus_cfg = limits.get("search", {}).get("corpus", {})
    hard_max = corpus_cfg.get("hard_max_top_k", 20)
    sim_threshold = corpus_cfg.get("min_similarity_threshold", 0.40)
    top_k = min(top_k, hard_max)
    fetch_k = top_k * 2  # over-fetch so RRF has enough candidates to re-rank

    pool = await get_pool()

    # Detect whether the ts column (generated tsvector) is available.
    async with pool.acquire() as conn:
        has_ts = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'embeddings' AND column_name = 'ts'
            )
            """
        )

    rows: list = []
    display_scores: dict[int, tuple[float, str]] = {}  # id → (score, label)

    if has_ts:
        # ---- Hybrid path: vector + full-text, merged with RRF ----
        async with pool.acquire() as conn:
            vec_rows = await conn.fetch(
                """
                SELECT
                    e.id, e.content, e.metadata, c.chunk_index,
                    d.source, d.source_type,
                    1 - (e.embedding <=> $1::vector) AS similarity
                FROM embeddings e
                LEFT JOIN chunks c ON e.chunk_id = c.id
                LEFT JOIN documents d ON c.document_id = d.id
                WHERE 1 - (e.embedding <=> $1::vector) > $3
                ORDER BY e.embedding <=> $1::vector
                LIMIT $2
                """,
                query_vector, fetch_k, sim_threshold,
            )
            kw_rows = await conn.fetch(
                """
                SELECT
                    e.id, e.content, e.metadata, c.chunk_index,
                    d.source, d.source_type,
                    0.0::float AS similarity
                FROM embeddings e
                LEFT JOIN chunks c ON e.chunk_id = c.id
                LEFT JOIN documents d ON c.document_id = d.id,
                     plainto_tsquery('english', $1) AS query
                WHERE e.ts @@ query
                ORDER BY ts_rank(e.ts, query) DESC
                LIMIT $2
                """,
                query, fetch_k,
            )

        # RRF: score = Σ 1 / (60 + rank) across both result lists.
        rrf: dict[int, dict] = {}
        for rank, row in enumerate(vec_rows, 1):
            rid = row["id"]
            rrf[rid] = {"row": row, "score": 1.0 / (60 + rank)}
        for rank, row in enumerate(kw_rows, 1):
            rid = row["id"]
            rrf.setdefault(rid, {"row": row, "score": 0.0})
            rrf[rid]["score"] += 1.0 / (60 + rank)

        top_items = sorted(rrf.values(), key=lambda x: x["score"], reverse=True)[:top_k]
        rows = [item["row"] for item in top_items]
        for item in top_items:
            display_scores[item["row"]["id"]] = (item["score"], "hybrid")

    else:
        # ---- Vector-only path (pre-migration) ----
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    e.id, e.content, e.metadata, c.chunk_index,
                    d.source, d.source_type,
                    1 - (e.embedding <=> $1::vector) AS similarity
                FROM embeddings e
                LEFT JOIN chunks c ON e.chunk_id = c.id
                LEFT JOIN documents d ON c.document_id = d.id
                WHERE 1 - (e.embedding <=> $1::vector) > $3
                ORDER BY e.embedding <=> $1::vector
                LIMIT $2
                """,
                query_vector, top_k, sim_threshold,
            )
        for row in rows:
            display_scores[row["id"]] = (row["similarity"], "similarity")

        # ILIKE fallback when vector search returns nothing (not needed in hybrid
        # mode because the tsvector query already covers keyword matching).
        if not rows:
            logger.info("Vector search returned no results — trying keyword fallback")
            keywords = [w for w in query.split() if len(w) > 3][:5]
            if keywords:
                like_pattern = "%" + "%".join(keywords) + "%"
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        """
                        SELECT
                            e.id, e.content, e.metadata, c.chunk_index,
                            d.source, d.source_type,
                            0.0::float AS similarity
                        FROM embeddings e
                        LEFT JOIN chunks c ON e.chunk_id = c.id
                        LEFT JOIN documents d ON c.document_id = d.id
                        WHERE e.content ILIKE $1
                        ORDER BY d.updated_at DESC
                        LIMIT $2
                        """,
                        like_pattern, top_k,
                    )
                for row in rows:
                    display_scores[row["id"]] = (0.0, "keyword")

    if not rows:
        return "No relevant documents found in the knowledge corpus."

    results = []
    for row in rows:
        meta = row["metadata"] or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        source = row["source"] or meta.get("source", "unknown")
        doc_type = row["source_type"] or meta.get("type", "unknown")
        chunk_label = f" (chunk {row['chunk_index']})" if row["chunk_index"] is not None else ""
        # Truncate content to 400 chars to stay within GitHub Models' 8k input limit
        snippet = row["content"][:400].rstrip() + ("..." if len(row["content"]) > 400 else "")
        score, label = display_scores.get(row["id"], (0.0, "score"))
        # Indicate whether the source is a citable external URL or an internal ref
        is_external = source.startswith(("http://", "https://"))
        link_note = "(external URL — may cite)" if is_external else "(internal corpus ref — do NOT use as a blog link)"
        results.append(
            f"**[Corpus match \u2014 {label}: {score:.4f}]**\n"
            f"Source: {source}{chunk_label} {link_note}\n"
            f"Type: {doc_type}\n"
            f"Date: {meta.get('date', 'unknown')}\n\n"
            f"{snippet}"
        )
    return "\n\n---\n\n".join(results)


async def _index_document_impl(content: str, source: str, doc_type: str, date: str = "") -> str:
    """Raw implementation of index_document (callable directly without FunctionTool wrapper).

    Upserts the document record, replaces all existing chunks and embeddings
    for this source (safe to re-run), then stores new chunks and embeddings.

    Args:
        content: The full text content to index.
        source: Unique identifier for this document (URL, filename, or path).
        doc_type: Type of document — one of: research, article, pdf, email, webpage.
        date: ISO date string (YYYY-MM-DD) when the document was created or retrieved.
    """
    max_w, overlap_w = _get_chunk_params()
    chunks = _chunk_text(content, max_words=max_w, overlap_words=overlap_w)
    if not chunks:
        return "No content to index."

    vectors = embed_batch(chunks)
    pool = await get_pool()
    doc_date = date or str(_date.today())

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Upsert document record.
            # ON CONFLICT replaces the content + updated_at so re-indexing is
            # always safe and the document row reflects the latest version.
            doc_id = await conn.fetchval(
                """
                INSERT INTO documents (source, source_type, content, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (source) DO UPDATE
                    SET content = EXCLUDED.content,
                        source_type = EXCLUDED.source_type,
                        updated_at = NOW()
                RETURNING id
                """,
                source, doc_type, content,
            )

            # 2. Delete old chunks (cascades to their embeddings automatically).
            # Note: aggregate functions are not allowed in RETURNING, so we
            # count first then delete separately.
            deleted = await conn.fetchval(
                "SELECT COUNT(*) FROM chunks WHERE document_id = $1", doc_id
            ) or 0
            await conn.execute(
                "DELETE FROM chunks WHERE document_id = $1", doc_id
            )

            # 3. Insert new chunks and their embeddings in one batch.
            metadata = json.dumps({"source": source, "type": doc_type, "date": doc_date})
            for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
                chunk_id = await conn.fetchval(
                    """
                    INSERT INTO chunks (document_id, chunk_index, content)
                    VALUES ($1, $2, $3)
                    RETURNING id
                    """,
                    doc_id, i, chunk,
                )
                await conn.execute(
                    """
                    INSERT INTO embeddings (chunk_id, content, embedding, metadata)
                    VALUES ($1, $2, $3::vector, $4)
                    """,
                    chunk_id, chunk, vector, metadata,
                )

    notice = f" (replaced {deleted} stale chunks)" if deleted else ""
    return f"Indexed {len(chunks)} chunks from '{source}' into the knowledge corpus{notice}."


@function_tool
async def index_document(content: str, source: str, doc_type: str, date: str = "") -> str:
    """Index a document into the knowledge corpus.

    Upserts the document record, replaces all existing chunks and embeddings
    for this source (safe to re-run), then stores new chunks and embeddings.

    Args:
        content: The full text content to index.
        source: Unique identifier for this document (URL, filename, or path).
        doc_type: Type of document — one of: research, article, pdf, email, webpage.
        date: ISO date string (YYYY-MM-DD) when the document was created or retrieved.
    """
    return await _index_document_impl(content, source, doc_type, date)


@function_tool
async def embed_and_store(text: str, source: str, metadata_json: str = "{}") -> str:
    """Embed a single pre-chunked text and store it in pgvector.

    Use this for individual chunks rather than full documents. For full
    documents, use index_document instead.

    Creates a proper document → chunk → embedding chain so the record is
    traceable via search_corpus.

    Args:
        text: The text chunk to embed and store.
        source: Source identifier for this chunk.
        metadata_json: JSON string with additional metadata (e.g. '{"type":"research"}').
    """
    vector = embed(text)  # list[float] — codec encodes automatically

    try:
        meta = json.loads(metadata_json)
    except json.JSONDecodeError:
        meta = {}
    meta.setdefault("source", source)
    meta.setdefault("date", str(_date.today()))
    doc_type = meta.get("type", "chunk")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Upsert a document record so this chunk is traceable
            doc_id = await conn.fetchval(
                """
                INSERT INTO documents (source, source_type, content, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (source) DO UPDATE
                    SET content = EXCLUDED.content,
                        updated_at = NOW()
                RETURNING id
                """,
                source, doc_type, text,
            )
            # Delete old chunks to avoid duplicates on re-run
            await conn.execute(
                "DELETE FROM chunks WHERE document_id = $1", doc_id
            )
            chunk_id = await conn.fetchval(
                """
                INSERT INTO chunks (document_id, chunk_index, content)
                VALUES ($1, 0, $2)
                RETURNING id
                """,
                doc_id, text,
            )
            await conn.execute(
                """
                INSERT INTO embeddings (chunk_id, content, embedding, metadata)
                VALUES ($1, $2, $3::vector, $4)
                """,
                chunk_id,
                text,
                vector,
                json.dumps(meta),
            )

    return f"Stored 1 chunk from '{source}'."


def _chunk_text(text: str, max_words: int = 200, overlap_words: int = 30) -> list[str]:
    """Split text into overlapping chunks at paragraph and section boundaries.

    Default max_words=200 matches the ~256-token input limit of
    all-MiniLM-L6-v2 so every chunk is fully represented by its embedding.
    """
    # Normalise section breaks (--- dividers, markdown headings) into
    # double-newlines so they act as split points
    normalised = _re.sub(r'\n---+\n', '\n\n', text)
    normalised = _re.sub(r'\n(#{1,3} )', r'\n\n\1', normalised)
    paragraphs = [p.strip() for p in normalised.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for para in paragraphs:
        para_words = len(para.split())
        if current_words + para_words > max_words and current:
            chunks.append("\n\n".join(current))
            # Build overlap: keep trailing text up to overlap_words
            if overlap_words > 0:
                overlap_paras: list[str] = []
                overlap_count = 0
                for p in reversed(current):
                    p_words = len(p.split())
                    if overlap_count + p_words > overlap_words and overlap_paras:
                        break
                    overlap_paras.insert(0, p)
                    overlap_count += p_words
                # If the last paragraph alone exceeds overlap_words, truncate it
                if len(overlap_paras) == 1 and overlap_count > overlap_words:
                    words = overlap_paras[0].split()
                    overlap_paras = [" ".join(words[-overlap_words:])]
                    overlap_count = overlap_words
                current = overlap_paras
                current_words = overlap_count
            else:
                current = []
                current_words = 0

        current.append(para)
        current_words += para_words

    if current:
        chunks.append("\n\n".join(current))

    return chunks
