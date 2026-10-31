"""Topic-aware source guidance and evidence checks before publication."""
import json
import logging
import re
from urllib.parse import urlsplit

from pipeline.config_loader import get_sources

logger = logging.getLogger(__name__)


def publisher(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if (
        host == "google.com"
        or host.endswith(".google.com")
        or host == "google.dev"
        or host.endswith(".google.dev")
        or host.endswith(".google")
    ):
        return "google"
    parts = host.split(".")
    size = 3 if host.endswith((".co.uk", ".org.uk", ".ac.uk", ".gov.uk", ".com")) else 2
    return ".".join(parts[-size:])


def diversify(items, url_for):
    """Round-robin publishers while retaining relevance order within each group."""
    groups = {}
    for item in items:
        groups.setdefault(publisher(url_for(item)), []).append(item)
    result = []
    while groups:
        for key in list(groups):
            result.append(groups[key].pop(0))
            if not groups[key]:
                del groups[key]
    return result


def ranked_sources(topic: str) -> list[dict]:
    """Rank configured domains by subject overlap, then primary status/credibility."""
    raw_terms = set(re.findall(r"[a-z]{2,}", topic.lower()))
    stop = {"the", "and", "are", "for", "what", "why", "how", "with", "from", "that",
            "this", "their", "about", "explore", "compared", "expected", "main", "open",
            "source", "sources", "beginner", "beginners", "guide", "guides", "need",
            "know", "difference", "between", "versus", "is", "of", "to", "in", "on",
            "at", "an", "as", "by", "be", "it", "or", "vs", "you", "your", "do",
            "does", "can", "should", "would", "will", "have", "has", "all"}
    terms = raw_terms - stop
    categories = set()
    for category, words in {
        "economics": {"financial", "finance", "debt", "liabilities", "revenue", "stocks", "equity", "investors", "credit", "inflation", "economy", "spending", "investment"},
        "climate": {"climate", "warming", "carbon", "emissions", "energy", "ocean", "weather"},
        "technology": {"technology", "intelligence", "computing", "semiconductor", "software", "ai", "llm", "hardware"},
        "policy": {"policy", "sanctions", "geopolitics", "regulation", "government"},
        "academic": {"science", "physics", "biology", "medicine", "neuroscience", "quantum"},
    }.items():
        if terms & words:
            categories.add(category)
    ranked = []
    for entry in get_sources().get("approved_domains", []):
        domain = entry.get("domain", "")
        if not domain:
            continue
        if entry.get("entities") and not any(entity.lower() in topic.lower() for entity in entry["entities"]):
            continue
        description = set(re.findall(
            r"[a-z]{2,}", (domain + " " + entry.get("notes", "")).lower()
        ))
        overlap = len(terms & description)
        category_bonus = 2 if entry.get("category") in categories else 0
        score = overlap * 3 + category_bonus
        if score and entry.get("primary"):
            score += 4
        if score:
            ranked.append((score, bool(entry.get("primary")), entry.get("credibility", 0), domain, entry))
    ranked.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
    # One domain per publisher; aliases/subdomains are not independent evidence.
    result, seen = [], set()
    for *_, entry in ranked:
        key = publisher("https://" + entry["domain"])
        if key not in seen:
            result.append(entry)
            seen.add(key)
    return result


def source_guidance(topic: str) -> str:
    entries = ranked_sources(topic)[:10]
    return (
        "Select pages directly relevant to this topic from the approved sources only. "
        "These candidates are ranked by subject overlap; the full approved list remains available. "
        "An approved domain is not proof that a particular page is relevant. "
        "Start with original documents for core facts; use reporting for context and scrutiny. "
        "Seek evidence for each major comparison subject, using comparable periods and metrics. "
        "There is no source-count quota: one supported finding can sustain a focused article. "
        "If evidence remains limited, narrow the argument and attribute the claims. "
        "Explain only limitations that materially change the conclusion, once.\n" +
        "\n".join(f'- {e["domain"]} ({e.get("credibility", 0)}/5): {e.get("notes", "")}' for e in entries)
    )


def _is_primary(source: dict) -> bool:
    host = urlsplit(source["url"]).hostname or ""
    for entry in get_sources().get("approved_domains", []):
        domain = entry.get("domain", "")
        if domain and entry.get("primary") and (host == domain or host.endswith("." + domain)):
            return True
    return source.get("evidence_role") == "primary"


def require_research_evidence(research_output: str) -> dict:
    """Keep a small sourced factual base; turn incomplete coverage into limitations."""
    from pipeline.tools.search import _is_approved
    try:
        data = json.loads(research_output)
        sources = {s["url"]: dict(s) for s in data.get("source_list", [])
                   if isinstance(s, dict) and isinstance(s.get("url"), str)}
        if not sources:
            raise ValueError("at least one relevant approved source is required")
        configured = get_sources().get("approved_domains", [])
        for url, source in sources.items():
            host = (urlsplit(url).hostname or "").lower()
            matches = [
                (len(entry["domain"]), entry.get("credibility", 0))
                for entry in configured
                if entry.get("domain") and (
                    host == entry["domain"] or host.endswith("." + entry["domain"])
                )
            ]
            score = max(matches)[1] if matches else source.get("credibility_score", 0)
            if not _is_approved(url) or not isinstance(score, (int, float)) or score < 3:
                raise ValueError("research includes unapproved or low-credibility evidence")
            source["credibility_score"] = score
            source["evidence_role"] = "primary" if _is_primary(source) else "secondary"

        gaps = [gap.strip() for gap in data.get("gaps", []) or []
                if isinstance(gap, str) and gap.strip()]
        findings = []
        for finding in data.get("key_findings", []):
            if not isinstance(finding, dict):
                continue
            refs = finding.get("sources")
            if (finding.get("finding") and isinstance(refs, list) and refs
                    and all(isinstance(url, str) and url in sources for url in refs)):
                findings.append(finding)
            elif finding.get("finding"):
                gaps.append("A finding without approved supporting evidence was omitted.")
        if not findings:
            raise ValueError("at least one finding needs approved supporting evidence")

        used = {u for f in findings for u in f.get("sources", []) if u in sources}
        if len({publisher(u) for u in used}) < 2:
            gaps.append("Findings rely on one publisher; attribute claims. Discuss limited corroboration only if it materially affects the conclusion.")
        coverage = []
        for item in data.get("question_coverage", []) or []:
            if not isinstance(item, dict):
                continue
            question = dict(item)
            refs = question.get("sources")
            if (question.get("status") not in {"answered", "partial"}
                    or not question.get("answer") or not isinstance(refs, list) or not refs
                    or not all(isinstance(url, str) and url in sources for url in refs)):
                question.update(
                    status="unanswered", sources=[],
                    answer="Not established by the retrieved evidence; omit unsupported claims or state that the answer is unknown.",
                )
            elif question.get("requires_primary") is True:
                supporting = [sources[u] for u in refs]
                if not any(_is_primary(s) for s in supporting):
                    question["status"] = "partial"
                    gaps.append("Primary evidence unavailable in retrieved research; attribute secondary reporting for: "
                                + str(question.get("question", "this question")))
            if question["status"] != "answered":
                gaps.append(f'{question["status"].capitalize()} evidence for: {question.get("question", "a requested question")}')
            coverage.append(question)
        if not coverage:
            gaps.append("Detailed question coverage is unavailable; restrict factual claims to the sourced findings.")
        if data.get("ready_to_write") is False:
            gaps.append("Research coverage is incomplete; scope the article to supported findings and explain only material limits once.")

        data.update(
            source_list=list(sources.values()), total_sources=len(sources),
            key_findings=findings, question_coverage=coverage,
            gaps=list(dict.fromkeys(gaps)), ready_to_write=True,
        )
        if gaps:
            logger.info("Evidence permits a scoped article with %d approved source(s) and disclosed limitations", len(sources))
        return data
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise RuntimeError(f"Research evidence insufficient: {exc}; retain research and defer writing/publication") from exc


def require_article_evidence(content: str, research_output: str) -> None:
    """Require visible citations to approved research without a publisher quota."""
    data = require_research_evidence(research_output)
    import markdown
    from html.parser import HTMLParser

    def normalise(url):
        return url.split("#", 1)[0].rstrip("/")

    class Citations(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = set()
            self.hidden = 0

        def handle_starttag(self, tag, attrs):
            if tag in {"pre", "code", "script", "style"}:
                self.hidden += 1
            if tag == "a" and not self.hidden:
                url = dict(attrs).get("href", "") or ""
                if url.startswith(("https://", "http://")):
                    self.links.add(normalise(url))

        def handle_endtag(self, tag):
            if tag in {"pre", "code", "script", "style"}:
                self.hidden = max(0, self.hidden - 1)

    if content.startswith("---"):
        content = content.split("---", 2)[-1]
    parser = Citations()
    parser.feed(markdown.markdown(content, extensions=["extra", "sane_lists"]))
    links = parser.links
    used = {u for f in data["key_findings"] for u in f.get("sources", [])}
    used.update(u for q in data["question_coverage"] for u in q.get("sources", []))
    sources = {normalise(s["url"]) for s in data["source_list"] if s["url"] in used}
    if not links or not links <= sources:
        raise RuntimeError("Article citations must come from its approved research evidence; defer publication")


def require_publish_file(path, research_output: str | None = None, *, content: str | None = None) -> None:
    if research_output is None:
        cache = path.with_name(path.stem.removesuffix("-edited") + "-research.json")
        if not cache.is_file():
            raise RuntimeError("No research evidence file for this article; research it before publishing")
        research_output = cache.read_text(encoding="utf-8")
    require_article_evidence(content if content is not None else path.read_text(encoding="utf-8"), research_output)
