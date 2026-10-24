"""Topic-aware source guidance and evidence checks before publication."""
import json
import re
from urllib.parse import urlsplit

from pipeline.config_loader import get_sources


def publisher(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    parts = host.split(".")
    size = 3 if host.endswith((".co.uk", ".org.uk", ".ac.uk", ".gov.uk", ".com.au")) else 2
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
    stop = {"the", "and", "are", "for", "what", "why", "how", "with", "from", "that",
            "this", "their", "about", "explore", "compared", "expected", "main"}
    terms = set(re.findall(r"[a-z]{3,}", topic.lower())) - stop
    categories = set()
    for category, words in {
        "economics": {"financial", "finance", "debt", "liabilities", "revenue", "stocks", "equity", "investors", "credit", "inflation", "economy"},
        "climate": {"climate", "warming", "carbon", "emissions", "energy", "ocean", "weather"},
        "technology": {"technology", "intelligence", "computing", "semiconductor", "software"},
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
        description = set(re.findall(r"[a-z]{3,}", (domain + " " + entry.get("notes", "")).lower()))
        overlap = len(terms & description)
        score = overlap * 3 + (2 if entry.get("category") in categories else 0)
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
        "Choose evidence for each requested question, not merely the first accessible outlet. "
        "Use primary documents for figures, independent reporting for corroboration, and "
        "different publishers for competing interpretations. These are candidates, not mandatory citations; "
        "the full approved list remains available.\n" +
        "\n".join(f'- {e["domain"]} ({e.get("credibility", 0)}/5): {e.get("notes", "")}' for e in entries)
    )


def _needs_primary(question: dict) -> bool:
    text = question.get("question", "").lower()
    return question.get("requires_primary") is True or bool(
        re.search(r"liabilit|\bdebt\b", text) and re.search(r"revenue|cash flow", text))


def _is_primary(source: dict) -> bool:
    host = urlsplit(source["url"]).hostname or ""
    for entry in get_sources().get("approved_domains", []):
        domain = entry.get("domain", "")
        if domain and entry.get("primary") and (host == domain or host.endswith("." + domain)):
            return True
    return source.get("evidence_role") == "primary"


def require_research_evidence(research_output: str) -> dict:
    """Validate declared evidence/coverage, not semantic truth or source independence."""
    from pipeline.tools.search import _is_approved
    try:
        data = json.loads(research_output)
        sources = {s["url"]: s for s in data.get("source_list", [])
                   if isinstance(s, dict) and isinstance(s.get("url"), str)}
        if len(sources) < 3:
            raise ValueError("at least three credible sources are required")
        for url, source in sources.items():
            score = source.get("credibility_score", 0)
            if not _is_approved(url) or not isinstance(score, (int, float)) or score < 3:
                raise ValueError("research includes unapproved or low-credibility evidence")
        findings = data.get("key_findings", [])
        if not findings or any(not f.get("finding") or not f.get("sources") or
                               not set(f["sources"]) <= sources.keys() for f in findings):
            raise ValueError("each finding needs approved supporting evidence")
        used = {u for f in findings for u in f.get("sources", []) if u in sources}
        if len({publisher(u) for u in used}) < 2:
            raise ValueError("findings need evidence from at least two publishers; extra unused URLs do not count")
        coverage = data.get("question_coverage", [])
        if data.get("ready_to_write") is not True or not coverage or not any(q.get("essential") is True for q in coverage):
            raise ValueError("missing assessment of the requested questions")
        for question in coverage:
            if question.get("essential") is True and (
                question.get("status") != "answered" or not question.get("answer") or
                not question.get("sources") or not set(question["sources"]) <= sources.keys()
            ):
                raise ValueError("an essential requested question remains unanswered")
            if question.get("essential") is True and _needs_primary(question):
                supporting = [sources[u] for u in question.get("sources", []) if u in sources]
                if not any(_is_primary(s) for s in supporting):
                    raise ValueError("an essential question needs primary evidence, not news commentary alone")
        return data
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise RuntimeError(f"Research evidence insufficient: {exc}; retain research and defer writing/publication") from exc


def require_article_evidence(content: str, research_output: str) -> None:
    """Check that published citations use the approved evidence, across publishers."""
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
    if len({publisher(u) for u in links}) < 2:
        raise RuntimeError("Article still cites only one publisher; defer publication")
    for question in data["question_coverage"]:
        if question.get("essential") is True and _needs_primary(question):
            primary = {normalise(s["url"]) for s in data["source_list"]
                       if s["url"] in question.get("sources", []) and _is_primary(s)}
            if not primary & links:
                raise RuntimeError("Article omits primary evidence for an essential question; defer publication")


def require_publish_file(path, research_output: str | None = None, *, content: str | None = None) -> None:
    if research_output is None:
        cache = path.with_name(path.stem.removesuffix("-edited") + "-research.json")
        if not cache.is_file():
            raise RuntimeError("No research evidence file for this article; research it before publishing")
        research_output = cache.read_text(encoding="utf-8")
    require_article_evidence(content if content is not None else path.read_text(encoding="utf-8"), research_output)
