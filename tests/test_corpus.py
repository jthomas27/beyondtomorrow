"""
tests/test_corpus.py — Unit tests for pipeline/tools/corpus.py

Covers:
    _chunk_text          — paragraph-boundary chunking with word overlap
    search_corpus        — semantic similarity search (mocked DB)
    index_document       — upsert + chunk + embed pipeline (mocked DB)
    embed_and_store      — single-chunk direct storage (mocked DB)

DB calls are mocked via pytest-mock; sentence-transformers runs locally.
"""

import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

from pipeline.tools.corpus import (
    _chunk_text,
    search_corpus,
    index_document,
    embed_and_store,
)
from tests.conftest import call_tool


# ---------------------------------------------------------------------------
# _chunk_text — pure function, no mocking needed
# ---------------------------------------------------------------------------

def test_chunk_text_empty_input_returns_empty_list():
    assert _chunk_text("") == []
    assert _chunk_text("   ") == []


def test_chunk_text_single_short_paragraph_returns_one_chunk():
    text = "This is a single short paragraph with just a few words."
    chunks = _chunk_text(text, max_words=500)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_splits_at_paragraph_boundary_when_limit_reached():
    """Two paragraphs that together exceed max_words must be split."""
    # Create a paragraph of ~300 words
    para_a = " ".join(["word"] * 300)
    para_b = " ".join(["word"] * 300)
    text = f"{para_a}\n\n{para_b}"

    chunks = _chunk_text(text, max_words=400, overlap_words=0)
    assert len(chunks) == 2
    assert para_a in chunks[0]
    assert para_b in chunks[1]


def test_chunk_text_single_chunk_when_text_fits():
    """Content under max_words must stay as one chunk regardless of paragraphs."""
    short_paras = "\n\n".join(["Short paragraph."] * 3)
    chunks = _chunk_text(short_paras, max_words=500)
    assert len(chunks) == 1


def test_chunk_text_overlap_repeats_last_paragraph():
    """With overlap enabled the last paragraph of each chunk opens the next.

    The chunker flushes when adding the next paragraph would exceed max_words,
    then seeds the next chunk with the last paragraph from the chunk just
    flushed.  Trace with max_words=300 and each para = 200 words:

        Process para_a (200w): current=[a], words=200
        Process para_b (200w): 200+200>300 → flush chunk0=[a],
                               seed=[a], words=200, then append b → [a,b], 400w
        Process para_c (200w): 400+200>300 → flush chunk1=[a,b],
                               seed=[b], words=200, then append c → [b,c], 400w
        End: flush chunk2=[b,c]

    So chunks[0]='alpha only', chunks[1]='alpha+beta', chunks[2]='beta+gamma'.
    """
    para_a = " ".join(["alpha"] * 200)
    para_b = " ".join(["beta"] * 200)
    para_c = " ".join(["gamma"] * 200)
    text = f"{para_a}\n\n{para_b}\n\n{para_c}"

    chunks = _chunk_text(text, max_words=300, overlap_words=50)
    assert len(chunks) == 3
    # chunk[0] is para_a only (flushed before overlap machinery kicks in)
    assert "alpha" in chunks[0]
    assert "beta" not in chunks[0]
    # chunk[1] = para_a (overlap) + para_b
    assert "alpha" in chunks[1]
    assert "beta" in chunks[1]
    # chunk[2] = para_b (overlap) + para_c
    assert "beta" in chunks[2]
    assert "gamma" in chunks[2]


def test_chunk_text_strips_whitespace_from_paragraphs():
    """Leading/trailing whitespace around paragraphs should be stripped."""
    text = "  First paragraph.  \n\n  Second paragraph.  "
    chunks = _chunk_text(text, max_words=500)
    assert chunks[0].startswith("First")
    assert not chunks[0].endswith("  ")


# ---------------------------------------------------------------------------
# search_corpus — semantic search (mocked DB)
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_db_row():
    """A dict-like row as asyncpg would return it."""
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=lambda k: {
        "content": "Climate tipping points may be closer than models predict.",
        "metadata": json.dumps({"source": "https://nature.com/1", "type": "article", "date": "2024-01-15"}),
        "chunk_index": 0,
        "source": "https://nature.com/1",
        "source_type": "article",
        "similarity": 0.87,
    }[k])
    return row


def _make_pool_mock(mocker, conn):
    """Build a pool mock where acquire() is a regular MagicMock (not async)
    so that `async with pool.acquire() as conn` works correctly."""
    pool = mocker.MagicMock()  # regular mock — get_pool will be patched as AsyncMock
    acquire_cm = mocker.MagicMock()
    acquire_cm.__aenter__ = mocker.AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = mocker.AsyncMock(return_value=False)
    pool.acquire = mocker.MagicMock(return_value=acquire_cm)
    return pool


@pytest.mark.asyncio
async def test_search_corpus_no_results_returns_informative_message(mocker):
    """When no rows match the similarity threshold the tool says so."""
    mock_conn = mocker.AsyncMock()
    mock_conn.fetch = mocker.AsyncMock(return_value=[])
    pool = _make_pool_mock(mocker, mock_conn)

    with patch("pipeline.tools.corpus.get_pool", mocker.AsyncMock(return_value=pool)), \
         patch("pipeline.tools.corpus.embed", return_value=[0.0] * 384):
        result = await call_tool(search_corpus, query="obscure topic with no matches", top_k=5)

    assert "No relevant documents" in result


@pytest.mark.asyncio
async def test_search_corpus_formats_single_result(mocker, fake_db_row):
    """A matching row should be formatted with source, similarity, and content."""
    mock_conn = mocker.AsyncMock()
    mock_conn.fetch = mocker.AsyncMock(return_value=[fake_db_row])
    pool = _make_pool_mock(mocker, mock_conn)

    with patch("pipeline.tools.corpus.get_pool", mocker.AsyncMock(return_value=pool)), \
         patch("pipeline.tools.corpus.embed", return_value=[0.0] * 384):
        result = await call_tool(search_corpus, query="climate tipping", top_k=5)

    assert "0.870" in result
    assert "https://nature.com/1" in result
    assert "Climate tipping points" in result


@pytest.mark.asyncio
async def test_search_corpus_embeds_the_query(mocker, fake_db_row):
    """search_corpus must embed the query text before hitting the DB."""
    mock_conn = mocker.AsyncMock()
    mock_conn.fetch = mocker.AsyncMock(return_value=[])
    pool = _make_pool_mock(mocker, mock_conn)

    mock_embed = mocker.MagicMock(return_value=[0.1] * 384)

    with patch("pipeline.tools.corpus.get_pool", mocker.AsyncMock(return_value=pool)), \
         patch("pipeline.tools.corpus.embed", mock_embed):
        await call_tool(search_corpus, query="ocean acidification", top_k=3)

    mock_embed.assert_called_once_with("ocean acidification")


# ---------------------------------------------------------------------------
# index_document — chunk + embed + upsert pipeline (mocked DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_index_document_reports_chunk_count(mocker):
    """index_document must report how many chunks were stored."""
    content = "Artificial intelligence is transforming every sector.\n\n" * 10

    mock_conn = mocker.AsyncMock()
    # fetchval returns: doc_id=42, then deleted=0, then chunk_id per chunk
    mock_conn.fetchval = mocker.AsyncMock(side_effect=[42, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9])

    txn_cm = mocker.MagicMock()
    txn_cm.__aenter__ = mocker.AsyncMock(return_value=None)
    txn_cm.__aexit__ = mocker.AsyncMock(return_value=False)
    mock_conn.transaction = mocker.MagicMock(return_value=txn_cm)

    pool = _make_pool_mock(mocker, mock_conn)

    with patch("pipeline.tools.corpus.get_pool", mocker.AsyncMock(return_value=pool)), \
         patch("pipeline.tools.corpus.embed_batch", return_value=[[0.0] * 384] * 5):
        result = await call_tool(
            index_document,
            content=content,
            source="https://example.com/ai-paper",
            doc_type="article",
            date="2025-01-01",
        )

    assert "Indexed" in result
    assert "https://example.com/ai-paper" in result
    assert "chunks" in result


@pytest.mark.asyncio
async def test_index_document_empty_content_returns_early(mocker):
    """Empty content should bail out without touching the DB."""
    mock_pool = mocker.MagicMock()

    with patch("pipeline.tools.corpus.get_pool", mocker.AsyncMock(return_value=mock_pool)):
        result = await call_tool(
            index_document,
            content="   ",
            source="https://example.com/empty",
            doc_type="webpage",
        )

    assert "No content" in result
    mock_pool.acquire.assert_not_called()


# ---------------------------------------------------------------------------
# embed_and_store — single chunk direct storage (mocked DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_embed_and_store_inserts_one_row(mocker):
    """embed_and_store must execute exactly one INSERT into embeddings."""
    mock_conn = mocker.AsyncMock()
    pool = _make_pool_mock(mocker, mock_conn)

    with patch("pipeline.tools.corpus.get_pool", mocker.AsyncMock(return_value=pool)), \
         patch("pipeline.tools.corpus.embed", return_value=[0.1] * 384):
        result = await call_tool(
            embed_and_store,
            text="Methane hydrates represent a significant climate feedback risk.",
            source="https://science.org/methane-study",
            metadata_json='{"type": "research"}',
        )

    assert "Stored 1 chunk" in result
    mock_conn.execute.assert_called_once()
    insert_sql = mock_conn.execute.call_args[0][0]
    assert "embeddings" in insert_sql.lower()


@pytest.mark.asyncio
async def test_embed_and_store_handles_invalid_metadata_json(mocker):
    """Malformed metadata_json should not raise — defaults to empty dict."""
    mock_conn = mocker.AsyncMock()
    pool = _make_pool_mock(mocker, mock_conn)

    with patch("pipeline.tools.corpus.get_pool", mocker.AsyncMock(return_value=pool)), \
         patch("pipeline.tools.corpus.embed", return_value=[0.0] * 384):
        result = await call_tool(
            embed_and_store,
            text="Some research text.",
            source="https://example.com/research",
            metadata_json="{NOT_VALID_JSON}",
        )

    assert "Stored 1 chunk" in result
