"""Evidence handoffs preserve useful facts without imposing source quotas."""
import json

from pipeline.source_policy import require_research_evidence, require_article_evidence
from pipeline.workflows.evidence import _compact_research


def test_long_coverage_does_not_displace_findings_or_source_roles():
    sources = [{"url": f"https://example.test/company-{i}",
                "title": f"Company {i} results", "evidence_role": "primary"}
               for i in range(4)]
    data = {
        "source_list": sources,
        "key_findings": [{"finding": f"Company {i} revenue rose {i + 1}% in Q3.",
                          "confidence": "high", "sources": [s["url"]]}
                         for i, s in enumerate(sources)],
        "question_coverage": [{"question": "Broad comparison", "answer": "padding " * 3000}],
        "gaps": ["Margin definitions differ."],
        "suggested_angles": ["padding " * 3000],
    }
    context = _compact_research(json.dumps(data), max_chars=1800)
    for i, source in enumerate(sources):
        assert f"Company {i} revenue rose {i + 1}% in Q3." in context
        assert source["url"] in context
    assert "[primary]" in context
    assert "Margin definitions differ." in context
    assert len(context) <= 1800
    assert "Context abridged" in context


def test_oversized_finding_is_omitted_whole_while_later_evidence_survives():
    data = {"key_findings": [
        {"finding": "oversized " * 2000, "sources": ["https://example.test/huge"]},
        {"finding": "A complete later finding.", "sources": ["https://example.test/later"]},
    ]}
    context = _compact_research(json.dumps(data), max_chars=600)
    assert "oversized" not in context
    assert "A complete later finding." in context
    assert "https://example.test/later" in context
    assert len(context) <= 600


def test_one_secondary_source_with_partial_coverage_still_proceeds():
    url = "https://www.cnbc.com/reported-results"
    data = {
        "source_list": [{"url": url, "evidence_role": "secondary"}],
        "key_findings": [{"finding": "A reported result.", "sources": [url]}],
        "question_coverage": [{"question": "What is the original figure?",
                               "requires_primary": True, "status": "answered",
                               "answer": "A reported result.", "sources": [url]}],
        "ready_to_write": False,
    }
    checked = require_research_evidence(json.dumps(data))
    assert checked["ready_to_write"] is True
    assert checked["question_coverage"][0]["status"] == "partial"
    assert checked["source_list"][0]["evidence_role"] == "secondary"
    require_article_evidence(f"A reported result, according to [CNBC]({url}).", json.dumps(checked))


def test_all_agent_prompts_use_the_configured_instructions():
    from pipeline import definitions
    for name in ("researcher", "writer", "editor", "publisher", "indexer", "orchestrator"):
        assert getattr(definitions, name).instructions == definitions._prompts[name]
