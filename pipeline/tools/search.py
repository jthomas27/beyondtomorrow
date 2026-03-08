"""
agents/tools/search.py — Web search, arXiv, and page fetching tools

Tools:
    web_search(query, max_results)  — DuckDuckGo text search
    search_arxiv(query, max_results) — arXiv academic paper search
    fetch_page(url)                 — Full-text extraction via trafilatura
"""

import httpx
import trafilatura
from pipeline._sdk import function_tool
from duckduckgo_search import DDGS


@function_tool
async def web_search(query: str, max_results: int = 10) -> str:
    """Search the web using DuckDuckGo. Returns titles, URLs, and snippets.

    Args:
        query: The search query string.
        max_results: Maximum number of results to return (default 10).
    """
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))

    if not results:
        return f"No results found for: {query}"

    return "\n\n".join(
        f"**{r['title']}**\n{r['href']}\n{r['body']}"
        for r in results
    )


@function_tool
async def search_arxiv(query: str, max_results: int = 5) -> str:
    """Search arXiv for academic papers. Returns titles, abstracts, and links.

    Args:
        query: The search query for academic papers.
        max_results: Maximum number of papers to return (default 5).
    """
    try:
        import arxiv
    except ImportError:
        return "arxiv package not installed. Run: pip install arxiv"

    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    results = []
    for paper in client.results(search):
        results.append(
            f"**{paper.title}**\n"
            f"URL: {paper.entry_id}\n"
            f"Published: {paper.published.strftime('%Y-%m-%d')}\n"
            f"Abstract: {paper.summary[:500]}"
        )
    return "\n\n---\n\n".join(results) if results else "No arXiv results found."


@function_tool
async def fetch_page(url: str) -> str:
    """Fetch a web page and extract the main article text (strips ads, nav, boilerplate).

    Args:
        url: The URL of the web page to fetch and extract text from.
    """
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
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

    # Truncate to ~4000 tokens to stay within context budget
    max_chars = 16_000
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[... truncated]"

    return f"Source: {url}\n\n{text}"
