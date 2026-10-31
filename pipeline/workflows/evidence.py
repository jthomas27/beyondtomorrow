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
    """Budget complete evidence records before editorial context.

    Keep source roles beside each finding so a truncated source appendix cannot
    lose provenance. Reserve space for coverage and uncertainty without letting
    repeated gaps displace the factual base. Never cut a claim or URL mid-record.
    """
    import json as _json

    try:
        data = _json.loads(research_output)
    except Exception:
        # Not JSON — just truncate with a note
        return research_output[:max_chars] + ("\n[truncated]" if len(research_output) > max_chars else "")

    def _is_external_url(url: str) -> bool:
        """Return True only for http/https URLs (not file paths or corpus refs)."""
        return isinstance(url, str) and url.startswith(("http://", "https://"))

    sources = {s["url"]: s for s in data.get("source_list", [])
               if _is_external_url(s.get("url", ""))}

    def citations(urls):
        result = []
        for url in urls:
            if _is_external_url(url):
                source = sources.get(url, {})
                result.append(f'{source.get("title", "Source")} '
                              f'[{source.get("evidence_role", "role unknown")}] {url}')
        return "; ".join(result)

    groups = {
        "KEY FINDINGS": [
            f'- {f.get("finding", "")} [{f.get("confidence", "unknown")}] '
            f'({citations(f.get("sources", []))})'
            for f in data.get("key_findings", [])
        ],
        "GAPS / UNCERTAINTY (editorial context; disclose only material limits once)": [
            f"- {gap}" for gap in dict.fromkeys(data.get("gaps", []) or [])
        ],
        "REQUESTED QUESTIONS / EVIDENCE": [
            f'- {q.get("question", "")}: {q.get("answer", "")} '
            f'[{q.get("status", "unknown")}] ({citations(q.get("sources", []))})'
            for q in data.get("question_coverage", [])
        ],
        "SUGGESTED ANGLES / SUBTOPICS": [
            *[f"- {angle}" for angle in data.get("suggested_angles", [])],
            *[f'- {s.get("name", "")}: {"; ".join(s.get("bullet_points", []))}'
              for s in data.get("subtopics", [])],
        ],
    }
    note = "\n[Context abridged; use search_corpus for omitted evidence before making additional claims.]"
    budget = max(0, max_chars - len(note))
    selected = {name: [] for name in groups}
    remaining = {name: [] for name in groups}
    used = 0

    def add(name, line, allowance):
        nonlocal used
        cost = len(line) + 1 + (len(name) + 4 if not selected[name] else 0)
        if cost > allowance or used + cost > budget:
            return False
        selected[name].append(line)
        used += cost
        return True

    # Reserve most space for facts, plus a small share for meaningful uncertainty.
    for (name, lines), share in zip(groups.items(), (0.70, 0.10, 0.15, 0.05)):
        start = used
        for line in lines:
            if not add(name, line, int(budget * share) - (used - start)):
                remaining[name].append(line)
    # Reuse unused allocations, prioritising complete findings and their sources.
    omitted = False
    for name, lines in remaining.items():
        for line in lines:
            if not add(name, line, budget - used):
                omitted = True
    compact = "\n\n".join(name + ":\n" + "\n".join(lines)
                           for name, lines in selected.items() if lines)
    if omitted:
        compact += note
    return compact[:max_chars] if max_chars < len(note) else compact

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
