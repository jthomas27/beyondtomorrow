"""Quick smoke tests for the new text processing functions."""

from pipeline.tools.files import _validate_punctuation, _enforce_british_english
from pipeline.guardrails import score_readability


def test_validate_punctuation():
    t = "Hello  world .  This is  a test. Some sentence."
    r = _validate_punctuation(t)
    assert "  " not in r, f"Double spaces remain: {r!r}"
    assert " ." not in r, f"Space before period: {r!r}"
    print(f"validate_punct OK: {r!r}")


def test_enforce_british_english():
    t = "We should analyze the behavior of the organization before we optimize."
    r = _enforce_british_english(t)
    assert "analyse" in r, f"Expected analyse: {r!r}"
    assert "behaviour" in r, f"Expected behaviour: {r!r}"
    assert "organisation" in r, f"Expected organisation: {r!r}"
    assert "optimise" in r, f"Expected optimise: {r!r}"
    print(f"british_english OK: {r!r}")


def test_case_preservation():
    t = "Analyze this. The Organization is large."
    r = _enforce_british_english(t)
    assert "Analyse" in r, f"Expected capitalised Analyse: {r!r}"
    assert "Organisation" in r, f"Expected capitalised Organisation: {r!r}"
    print(f"case_preserve OK: {r!r}")


def test_url_preservation():
    t = "We will [analyze behavior](https://example.com/analyze/behavior)"
    r = _enforce_british_english(t)
    # Text portion should be British
    text_part = r.split("](")[0]
    assert "analyse" in text_part.lower(), f"Text should be British: {r!r}"
    # URL should NOT be changed
    assert "analyze/behavior" in r, f"URL should be unchanged: {r!r}"
    print(f"url_preserve OK: {r!r}")


def test_readability():
    sample = (
        "---\ntitle: Test Post\ntags: test\nexcerpt: A test.\n---\n\n"
        "## Introduction\n\n"
        "Climate change is the defining challenge of our generation. "
        "The planet has warmed by approximately 1.1 degrees Celsius since "
        "pre-industrial times, and the consequences are accelerating. "
        "From devastating wildfires in Australia to unprecedented flooding "
        "in Europe, the evidence is impossible to ignore.\n\n"
        "## The Science\n\n"
        "Scientists have been warning us for decades. The Intergovernmental "
        "Panel on Climate Change has published six major assessment reports, "
        "each more alarming than the last. Carbon dioxide levels have reached "
        "420 parts per million.\n\n"
        "## What Now\n\n"
        "The question is not whether we need to act, but how fast. Every "
        "fraction of a degree matters. The choices we make in the next decade "
        "will determine the climate our grandchildren inherit.\n\n"
        "## Just For Laughs\n\n"
        "Why did the climate scientist break up with the weather forecaster? "
        "Because their relationship had no future.\n"
    )
    m = score_readability(sample)
    print(
        f"Readability: words={m['word_count']}, sentences={m['sentence_count']}, "
        f"avg_len={m['avg_sentence_len']}, flesch={m['flesch_score']}, "
        f"grade={m['grade_label']}"
    )
    for w in m["warnings"]:
        print(f"  WARNING: {w}")
    assert m["word_count"] > 0
    assert m["flesch_score"] > 0
    print("readability OK")


if __name__ == "__main__":
    test_validate_punctuation()
    test_enforce_british_english()
    test_case_preservation()
    test_url_preservation()
    test_readability()
    print("\nAll tests passed.")
