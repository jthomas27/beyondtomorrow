"""
agents/tools/__init__.py — Tool registry

Imports all @function_tool decorated tools so agent definitions can import
from a single location:

    from pipeline.tools import web_search, search_corpus, publish_to_ghost, ...
"""

from pipeline.tools.search import web_search, search_arxiv, fetch_page
from pipeline.tools.corpus import search_corpus, index_document, embed_and_store
from pipeline.tools.ghost import publish_to_ghost
from pipeline.tools.files import read_research_file, write_research_file
from pipeline.tools.quality import score_credibility

__all__ = [
    "web_search",
    "search_arxiv",
    "fetch_page",
    "search_corpus",
    "index_document",
    "embed_and_store",
    "publish_to_ghost",
    "read_research_file",
    "write_research_file",
    "score_credibility",
]
