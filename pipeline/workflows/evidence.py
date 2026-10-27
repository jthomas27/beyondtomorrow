"""Evidence workflow implementation."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from time import monotonic

from pipeline.paths import PROJECT_ROOT
from pipeline.workflows.common import _AGENT_TIMEOUT, _STAGE_COOLDOWN, _RETRY_BACKOFF_BASE

logger = logging.getLogger("pipeline")



def _valid_research_cache(path, *, require_evidence: bool = False) -> bool:
    """An older token-truncated cache must not poison every subsequent retry."""
    import json
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        valid = isinstance(data, dict) and isinstance(data.get("key_findings"), list) and isinstance(data.get("source_list"), list)
        if valid and require_evidence:
            _require_research_evidence(json.dumps(data))
        return valid
    except (OSError, ValueError, TypeError, RuntimeError):
        return False

def _require_research_evidence(research_output: str) -> str:
    import json
    from pipeline.source_policy import require_research_evidence
    return json.dumps(require_research_evidence(research_output), ensure_ascii=False, indent=2)

def _require_publish_evidence(path, research_output: str | None = None) -> None:
    from pipeline.source_policy import require_publish_file
    require_publish_file(path, research_output)

def _compact_research(research_output: str, max_chars: int = 3000) -> str:
    """Return a token-budget-friendly summary of the research JSON.

    Extracts the fields the writer/editor actually need (key_findings,
    suggested_angles, subtopics, source_list) and drops bulk like full
    summaries and redundant metadata.  Falls back to a plain truncation
    if the output is not valid JSON.
    """
    import json as _json

    try:
        data = _json.loads(research_output)
    except Exception:
        # Not JSON — just truncate with a note
        return research_output[:max_chars] + ("\n[truncated]" if len(research_output) > max_chars else "")

    parts: list[str] = []
    if data.get("gaps") or any(q.get("status") != "answered"
                             for q in data.get("question_coverage", [])):
        parts.append("EVIDENCE LIMITS: Use the sourced findings as the factual basis. "
                     "State material gaps and attribute claims with limited corroboration. "
                     "Omit unsupported details or explain that they are unknown. "
                     "Do not present unresolved questions as established facts.")
    if data.get("question_coverage"):
        parts.append("REQUESTED QUESTIONS / EVIDENCE:")
        for question in data["question_coverage"]:
            parts.append(f'- {question.get("question", "")}: {question.get("answer", "")} '
                         f'[{question.get("status", "unknown")}] ({", ".join(question.get("sources", []))})')

    def _is_external_url(url: str) -> bool:
        """Return True only for http/https URLs (not file paths or corpus refs)."""
        return isinstance(url, str) and url.startswith(("http://", "https://"))

    # Key findings — keep finding text, confidence, and external sources only
    findings = data.get("key_findings", [])
    if findings:
        parts.append("KEY FINDINGS:")
        for f in findings:
            ext_sources = [s for s in f.get("sources", []) if _is_external_url(s)]
            src = ", ".join(ext_sources[:2])
            conf = f.get("confidence", "unknown")
            parts.append(f"- {f.get('finding', '')} [{conf}] ({src})")

    gaps = data.get("gaps", [])
    if gaps:
        parts.append("\nGAPS / UNCERTAINTY:")
        parts.extend(f"- {gap}" for gap in gaps)

    # Suggested angles
    angles = data.get("suggested_angles", [])
    if angles:
        parts.append("\nSUGGESTED ANGLES:")
        for a in angles:
            parts.append(f"- {a}")

    # Subtopics — name + bullet points only, skip full summaries
    subtopics = data.get("subtopics", [])
    if subtopics:
        parts.append("\nSUBTOPICS:")
        for s in subtopics:
            parts.append(f"  {s.get('name', '')}:")
            for bp in s.get("bullet_points", []):
                parts.append(f"    • {bp}")

    # Source list — external URLs only (no corpus refs or file paths)
    sources = data.get("source_list", [])
    ext_sources = [s for s in sources if _is_external_url(s.get("url", ""))]
    if ext_sources:
        parts.append("\nSOURCES (external links only — use these for inline citations):")
        for src in ext_sources:
            parts.append(f"- {src.get('title', 'Untitled')}: {src.get('url', '')}")

    compact = "\n".join(parts)
    if len(compact) > max_chars:
        truncated = compact[:max_chars].rsplit("\n", 1)[0]
        compact = truncated + "\n[... truncated — use search_corpus for additional sources]"
    return compact

async def _sanitise_research_sources(research_json: str) -> str:
    """Strip dead/fabricated URLs from a research JSON string before indexing.

    LLMs sometimes hallucinate plausible-looking source URLs.  These get
    indexed into the corpus and re-cited by the Researcher on subsequent
    runs.  This function:

    1. Parses the research JSON.
    2. Collects every URL from ``source_list`` and ``key_findings[].sources``.
    3. Concurrently validates each URL with a HEAD request (5 s timeout).
    4. Removes any URL that returns 4xx/5xx, fails to connect, or is not
       an http/https URL.
    5. Returns the cleaned JSON string (or the original if parsing fails).

    Non-fatal — any exception returns the original string unchanged.
    """
    import json as _json
    import asyncio as _asyncio

    def _is_http(url: str) -> bool:
        return isinstance(url, str) and url.startswith(("http://", "https://"))

    try:
        data = _json.loads(research_json)
    except Exception:
        return research_json  # not JSON — leave unchanged

    # Collect all unique URLs that need checking
    all_urls: set[str] = set()
    for src in data.get("source_list", []):
        if _is_http(src.get("url", "")):
            all_urls.add(src["url"])
    for finding in data.get("key_findings", []):
        for url in finding.get("sources", []):
            if _is_http(url):
                all_urls.add(url)

    if not all_urls:
        return research_json

    # Validate URLs concurrently
    async def _check(url: str) -> tuple[str, bool]:
        from pipeline.tools.search import _is_approved, _get_approved_page
        if not _is_approved(url):
            return url, False
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(
                timeout=5.0,
                follow_redirects=False,
                headers={"User-Agent": "Mozilla/5.0 (compatible; BeyondTomorrow/1.0)"},
            ) as client:
                try:
                    resp = await client.head(url)
                    if resp.status_code >= 300:
                        resp = await _get_approved_page(client, url)
                except Exception:
                    resp = await _get_approved_page(client, url)  # some servers reject HEAD
                return url, resp.status_code < 400
        except Exception:
            return url, False

    results = await _asyncio.gather(*[_check(u) for u in all_urls], return_exceptions=False)
    dead = {url for url, ok in results if not ok}

    if not dead:
        return research_json  # all URLs live — no changes needed

    logger.info(
        "Stripping %d dead source URL(s) from research JSON: %s",
        len(dead), list(dead),
    )

    # Remove dead URLs from source_list
    data["source_list"] = [
        s for s in data.get("source_list", [])
        if s.get("url", "") not in dead
    ]
    data["total_sources"] = len(data.get("source_list", []))

    # Remove dead URLs from key_findings[].sources
    for finding in data.get("key_findings", []):
        finding["sources"] = [
            u for u in finding.get("sources", []) if u not in dead
        ]
    for question in data.get("question_coverage", []):
        question["sources"] = [u for u in question.get("sources", []) if u not in dead]
        if question.get("essential") is True and not question["sources"]:
            question["status"] = "unanswered"
            data["ready_to_write"] = False

    return _json.dumps(data, ensure_ascii=False, indent=2)
