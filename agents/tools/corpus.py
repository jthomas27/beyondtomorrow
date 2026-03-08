"""
agents/tools/corpus.py — pgvector knowledge corpus tools

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
from datetime import date as _date
from agents._sdk import function_tool
from agents.embeddings import embed, embed_batch
from agents.db import get_pool


@function_tool
async def search_corpus(query: str, top_k: int = 5) -> str:
    """Search the private knowledge corpus using semantic similarity (pgvector).

    Args:
        query: The search query — will be embedded and compared against stored documents.
        top_k: Number of most similar results to return (default 5).
    """
    query_vector = embed(query)  # list[float] — codec encodes automatically

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                e.content,
                e.metadata,
                c.chunk_index,
                d.source,
                d.source_type,
                1 - (e.embedding <=> $1::vector) AS similarity
            FROM embeddings e
            LEFT JOIN chunks c ON e.chunk_id = c.id
            LEFT JOIN documents d ON c.document_id = d.id
            WHERE 1 - (e.embedding <=> $1::vector) > 0.3
            ORDER BY e.embedding <=> $1::vector
            LIMIT $2
            """,
            query_vector,
            top_k,
        )

    if not rows:
        return "No relevant documents found in the knowledge corpus."

    results = []
    for row in rows:
        meta = row["metadata"] or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        # Prefer normalized document source over metadata fallback
        source = row["source"] or meta.get("source", "unknown")
        doc_type = row["source_type"] or meta.get("type", "unknown")
        chunk_label = f" (chunk {row['chunk_index']}" + ")" if row["chunk_index"] is not None else ""
        results.append(
            f"**[Corpus match — similarity: {row['similarity']:.3f}]**\n"
            f"Source: {source}{chunk_label}\n"
            f"Type: {doc_type}\n"
            f"Date: {meta.get('date', 'unknown')}\n\n"
            f"{row['content'][:2000]}"
        )
    return "\n\n---\n\n".join(results)


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
    chunks = _chunk_text(content, max_words=500, overlap_words=50)
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
            deleted = await conn.fetchval(
                "DELETE FROM chunks WHERE document_id = $1 RETURNING COUNT(*)",
                doc_id,
            ) or 0

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
async def embed_and_store(text: str, source: str, metadata_json: str = "{}") -> str:
    """Embed a single pre-chunked text and store it in pgvector.

    Use this for individual chunks rather than full documents. For full
    documents, use index_document instead.

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

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO embeddings (content, embedding, metadata)
            VALUES ($1, $2::vector, $3)
            """,
            text,
            vector,
            json.dumps(meta),
        )

    return f"Stored 1 chunk from '{source}'."


def _chunk_text(text: str, max_words: int = 500, overlap_words: int = 50) -> list[str]:
    """Split text into overlapping chunks at paragraph boundaries."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for para in paragraphs:
        para_words = len(para.split())
        if current_words + para_words > max_words and current:
            chunks.append("\n\n".join(current))
            # Keep last paragraph as overlap
            current = [current[-1]] if overlap_words > 0 else []
            current_words = len(current[0].split()) if current else 0

        current.append(para)
        current_words += para_words

    if current:
        chunks.append("\n\n".join(current))

    return chunks
