"""
agents/tools/search.py — Web search, arXiv, and page fetching tools

Tools:
    web_search(query, max_results)        — DuckDuckGo text search with auto-retry
    search_arxiv(query, max_results)      — arXiv academic paper search
    fetch_page(url)                       — Full-text extraction via trafilatura
    search_and_index(query, max_results)  — Search + fetch full pages + store to pgvector
"""

import asyncio
import json
import logging
from datetime import date as _date
from urllib.parse import urlparse

import httpx
import trafilatura
from pipeline._sdk import function_tool

logger = logging.getLogger(__name__)

try:
    from ddgs import DDGS          # new package name
except ImportError:
    from duckduckgo_search import DDGS  # legacy — still works during transition


# ---------------------------------------------------------------------------
# Cached config
# ---------------------------------------------------------------------------

_cached_limits: dict | None = None
_cached_sources: dict | None = None


def _get_limits() -> dict:
    global _cached_limits
    if _cached_limits is None:
        try:
            from pipeline.config_loader import get_limits
            _cached_limits = get_limits()
        except Exception:
            _cached_limits = {}
    return _cached_limits


def _get_approved_domains() -> set[str]:
    """Return the set of approved apex domains from sources.yaml."""
    global _cached_sources
    if _cached_sources is None:
        try:
            from pipeline.config_loader import get_sources
            _cached_sources = get_sources()
        except Exception:
            _cached_sources = {}
    domains = set()
    for entry in _cached_sources.get("approved_domains", []):
        d = entry.get("domain", "").lower().strip()
        if d:
            domains.add(d)
    return domains


def _domain_of(url: str) -> str:
    """Extract the apex-style domain from a URL (strips www.)."""
    host = urlparse(url).hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host.lower()


def _is_approved(url: str) -> bool:
    """Check if a URL's domain is in the approved list.

    Returns True if no approved domains are configured (permissive fallback).
    """
    approved = _get_approved_domains()
    if not approved:
        return True  # no allowlist configured — allow all
    domain = _domain_of(url)
    return any(domain == d or domain.endswith("." + d) for d in approved)


def _query_variants(query: str) -> list[str]:
    """Return progressively simplified query variants for rate-limit retry."""
    words = query.split()
    candidates = [
        query,
        " ".join(words[:min(6, len(words))]),
        " ".join(words[:min(4, len(words))]) + " 2024 2025",
    ]
    seen: set[str] = set()
    unique: list[str] = []
    for v in candidates:
        if v not in seen:
            seen.add(v)
            unique.append(v)
    return unique


def _ddg_text(query: str, max_results: int) -> list[dict]:
    """Run a single DuckDuckGo text search."""
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


@function_tool
async def web_search(query: str, max_results: int = 10) -> str:
    """Search the web using DuckDuckGo. Automatically retries with simplified
    terms if no results are returned (handles rate limiting gracefully).

    Args:
        query: The search query string.
        max_results: Maximum number of results to return (default 10).
    """
    for variant in _query_variants(query):
        results = _ddg_text(variant, max_results)
        if results:
            return "\n\n".join(
                f"**{r['title']}**\n{r['href']}\n{r['body']}"
                for r in results
            )
        await asyncio.sleep(2)

    return (
        f"No results found for '{query}' after multiple attempts. "
        "Try search_corpus to query the knowledge database, "
        "or use fetch_page with a known URL."
    )


async def _search_and_index_impl(query: str, max_results: int = 8) -> str:
    """Core implementation of search + embed + store. Called by the @function_tool
    wrapper and by _prefetch_topic (which runs outside the LLM loop)."""
    from pipeline.embeddings import embed_batch
    from pipeline.db import get_pool
    from pipeline.tools.corpus import _chunk_text, _get_chunk_params

    # Read config
    limits = _get_limits()
    fetch_cfg = limits.get("fetch", {})
    cfg_max_pages = fetch_cfg.get("max_pages_per_query", 8)
    cfg_timeout = fetch_cfg.get("request_timeout_seconds", 15)
    cfg_max_chars = fetch_cfg.get("max_content_chars_per_page", 16_000)
    max_w, overlap_w = _get_chunk_params()

    # Respect config cap on pages
    max_results = min(max_results, cfg_max_pages)

    # Step 1: Search with auto-retry on rate limit
    results: list[dict] = []
    used_variant = query
    for variant in _query_variants(query):
        results = _ddg_text(variant, max_results)
        if results:
            used_variant = variant
            break
        await asyncio.sleep(2)

    if not results:
        return (
            f"No web results found for '{query}' after multiple retry attempts. "
            "Use search_corpus to query existing knowledge, or try fetch_page with a direct URL."
        )

    today = str(_date.today())
    indexed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    # Pre-check which URLs were indexed recently (skip re-fetching)
    pool = await get_pool()
    urls = [r.get("href", "") for r in results if r.get("href")]
    recent_urls: set[str] = set()
    if urls:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT source FROM documents "
                "WHERE source = ANY($1) AND updated_at > NOW() - INTERVAL '7 days'",
                urls,
            )
            recent_urls = {row["source"] for row in rows}

    # Collect pages to index
    pages_to_store: list[dict] = []  # {url, title, text, chunks, vectors}

    async with httpx.AsyncClient(
        timeout=float(cfg_timeout),
        follow_redirects=True,
        headers={"User-Agent": "BeyondTomorrow-Research/1.0"},
    ) as client:
        for r in results:
            url = r.get("href", "")
            title = r.get("title", url)

            if url in recent_urls:
                indexed.append(f'"{title}" (cached)')
                continue

            # Filter out unapproved domains
            if not _is_approved(url):
                skipped.append(f"{title} (domain not approved)")
                continue

            # Fetch full page text; fall back to search snippet on failure
            text = ""
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                text = trafilatura.extract(
                    resp.text, include_comments=False, include_tables=True
                ) or ""
            except Exception as fetch_err:
                logger.warning("Failed to fetch %s: %s", url, fetch_err)
                failed.append(f"{title} ({fetch_err.__class__.__name__})")

            if len(text) < 100:
                text = r.get("body", "")  # snippet fallback
            if not text:
                skipped.append(title)
                continue

            if len(text) > cfg_max_chars:
                text = text[:cfg_max_chars] + "\n\n[... truncated]"

            # Chunk and embed (CPU-only, no DB yet)
            chunks = _chunk_text(text, max_words=max_w, overlap_words=overlap_w)
            if not chunks:
                continue
            vectors = embed_batch(chunks)
            pages_to_store.append({
                "url": url, "title": title, "text": text,
                "chunks": chunks, "vectors": vectors,
            })

    # Batch-write all pages in a single DB transaction
    if pages_to_store:
        metadata_base = {"type": "webpage", "date": today, "query": used_variant}
        async with pool.acquire() as conn:
            async with conn.transaction():
                for page in pages_to_store:
                    metadata = json.dumps({**metadata_base, "source": page["url"], "title": page["title"]})
                    doc_id = await conn.fetchval(
                        """
                        INSERT INTO documents (source, source_type, title, content, updated_at)
                        VALUES ($1, $2, $3, $4, NOW())
                        ON CONFLICT (source) DO UPDATE
                            SET content = EXCLUDED.content,
                                source_type = EXCLUDED.source_type,
                                title = EXCLUDED.title,
                                updated_at = NOW()
                        RETURNING id
                        """,
                        page["url"], "webpage", page["title"], page["text"],
                    )
                    await conn.execute(
                        "DELETE FROM chunks WHERE document_id = $1", doc_id
                    )
                    chunk_ids = await conn.fetch(
                        """
                        INSERT INTO chunks (document_id, chunk_index, content)
                        SELECT $1, unnest($2::int[]), unnest($3::text[])
                        RETURNING id
                        """,
                        doc_id,
                        list(range(len(page["chunks"]))),
                        page["chunks"],
                    )
                    await conn.executemany(
                        """
                        INSERT INTO embeddings (chunk_id, content, embedding, metadata)
                        VALUES ($1, $2, $3::vector, $4)
                        """,
                        [
                            (row["id"], chunk, vector, metadata)
                            for row, chunk, vector in zip(chunk_ids, page["chunks"], page["vectors"])
                        ],
                    )
                    indexed.append(f'"{page["title"]}"')

    lines = [f"Indexed {len(indexed)} pages into pgvector corpus (query: '{used_variant}')."]
    if indexed:
        lines.append("Pages stored: " + ", ".join(indexed[:5]))
        if len(indexed) > 5:
            lines.append(f"... and {len(indexed) - 5} more.")
    if skipped:
        lines.append(f"Skipped {len(skipped)} pages with no extractable text.")
    if failed:
        lines.append(f"Failed to fetch {len(failed)} pages: " + "; ".join(failed[:3]))
    lines.append("Use search_corpus to retrieve information from these pages.")
    return "\n".join(lines)


@function_tool
async def search_and_index(query: str, max_results: int = 8) -> str:
    """Search the web, fetch full page content, and store text + embeddings in pgvector.

    Unlike web_search (snippets only), this tool fetches complete article text and
    persists it in the knowledge corpus (PostgreSQL + pgvector) so it can be retrieved
    semantically by search_corpus. Results survive across pipeline runs — they are
    stored in the database, not temporary files.

    Automatically retries with simplified search terms if rate-limited.

    Args:
        query: The search query string.
        max_results: Number of pages to fetch and index (default 8).
    """
    return await _search_and_index_impl(query, max_results)


@function_tool
async def search_arxiv(query: str, max_results: int = 5) -> str:
    """Search arXiv for academic papers and index abstracts into the corpus.

    Returns titles, abstracts, and links. Also stores each abstract in
    pgvector so future search_corpus calls can retrieve them.

    Args:
        query: The search query for academic papers.
        max_results: Maximum number of papers to return (default 5).
    """
    try:
        import arxiv
    except ImportError:
        return "arxiv package not installed. Run: pip install arxiv"

    limits = _get_limits()
    arxiv_cfg = limits.get("search", {}).get("arxiv", {})
    hard_max = arxiv_cfg.get("hard_max_results", 10)
    max_results = min(max_results, hard_max)

    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    results = []
    papers_to_index: list[dict] = []
    for paper in client.results(search):
        results.append(
            f"**{paper.title}**\n"
            f"URL: {paper.entry_id}\n"
            f"Published: {paper.published.strftime('%Y-%m-%d')}\n"
            f"Abstract: {paper.summary[:500]}"
        )
        papers_to_index.append({
            "url": paper.entry_id,
            "title": paper.title,
            "abstract": paper.summary,
            "date": paper.published.strftime("%Y-%m-%d"),
        })

    # Index abstracts into the corpus for future retrieval
    if papers_to_index:
        try:
            from pipeline.embeddings import embed_batch
            from pipeline.db import get_pool
            import json as _json

            pool = await get_pool()
            texts = [p["abstract"] for p in papers_to_index]
            vectors = embed_batch(texts)
            today = str(_date.today())

            async with pool.acquire() as conn:
                async with conn.transaction():
                    for paper, vector in zip(papers_to_index, vectors):
                        metadata = _json.dumps({
                            "type": "arxiv", "source": paper["url"],
                            "title": paper["title"], "date": paper["date"],
                        })
                        doc_id = await conn.fetchval(
                            """
                            INSERT INTO documents (source, source_type, title, content, updated_at)
                            VALUES ($1, $2, $3, $4, NOW())
                            ON CONFLICT (source) DO UPDATE
                                SET content = EXCLUDED.content, title = EXCLUDED.title, updated_at = NOW()
                            RETURNING id
                            """,
                            paper["url"], "arxiv", paper["title"], paper["abstract"],
                        )
                        await conn.execute("DELETE FROM chunks WHERE document_id = $1", doc_id)
                        chunk_id = await conn.fetchval(
                            "INSERT INTO chunks (document_id, chunk_index, content) VALUES ($1, 0, $2) RETURNING id",
                            doc_id, paper["abstract"],
                        )
                        await conn.execute(
                            "INSERT INTO embeddings (chunk_id, content, embedding, metadata) VALUES ($1, $2, $3::vector, $4)",
                            chunk_id, paper["abstract"], vector, metadata,
                        )
            logger.info("Indexed %d arXiv abstracts into corpus", len(papers_to_index))
        except Exception as idx_err:
            logger.warning("Could not index arXiv papers to corpus: %s", idx_err)

    if not results:
        return "No arXiv results found."
    return "\n\n---\n\n".join(results)


@function_tool
async def fetch_page(url: str) -> str:
    """Fetch a web page and extract the main article text (strips ads, nav, boilerplate).

    Args:
        url: The URL of the web page to fetch and extract text from.
    """
    fetch_cfg = _get_limits().get("fetch", {})
    timeout = fetch_cfg.get("request_timeout_seconds", 15)
    try:
        async with httpx.AsyncClient(
            timeout=float(timeout),
            follow_redirects=True,
            headers={"User-Agent": "BeyondTomorrow-Research/1.0"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        return f"Failed to fetch {url}: {exc}"

    text = trafilatura.extract(resp.text, include_comments=False, include_tables=True)
    if not text:
        return f"Could not extract text from {url}"

    # Truncate to stay within context budget
    max_chars = fetch_cfg.get("max_content_chars_per_page", 16_000)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[... truncated]"

    return f"Source: {url}\n\n{text}"


# ---------------------------------------------------------------------------
# Pre-fetch helper — called directly by the pipeline (not via LLM tool call)
# ---------------------------------------------------------------------------

async def _prefetch_topic(topic: str, num_queries: int = 2) -> list[str]:
    """Generate simple keyword queries for *topic* and index pages into the corpus.

    This runs entirely outside the LLM loop — no API calls to GitHub Models.
    Pages are fetched and embedded before the Researcher agent starts, so the
    agent can skip search_and_index calls and go straight to search_corpus.

    Args:
        topic: The raw topic string from the pipeline task.
        num_queries: How many query variants to generate (default 2).

    Returns:
        List of index-result strings from search_and_index.
    """
    words = [w for w in topic.lower().replace(",", "").replace("'", "").split() if len(w) > 2]

    # Build simple keyword-only queries (no LLM needed)
    queries: list[str] = []
    # Query 1: First 5 meaningful words
    queries.append(" ".join(words[:5]))
    # Query 2: Append "analysis 2025" for a recency-focused angle
    if num_queries >= 2:
        queries.append(" ".join(words[:4]) + " analysis 2025")
    # Query 3: "latest" variant
    if num_queries >= 3:
        queries.append("latest " + " ".join(words[:4]))

    results: list[str] = []
    for q in queries[:num_queries]:
        try:
            result = await _search_and_index_impl(q, max_results=5)
            results.append(result)
            logger.info("Pre-fetch: indexed query '%s'", q)
        except Exception as exc:
            logger.warning("Pre-fetch failed for query '%s': %s", q, exc)
        # Small delay between queries to avoid DuckDuckGo rate-limiting
        await asyncio.sleep(3)

    return results
