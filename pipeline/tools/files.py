"""
pipeline/tools/files.py — Research file I/O tools

Files are stored under research/ (drafts, edited posts, JSON findings) or
reports/ (external PDFs and reference documents) at the project root.
Paths are validated to prevent path traversal attacks.

Tools:
    read_research_file(filename)         — Read a file from research/ or reports/
    write_research_file(filename, content) — Write a file to research/
"""

import asyncio
import os
import pathlib
import random
import re
import html as _html
import httpx
from pipeline._sdk import function_tool

# Resolve research/ and reports/ directories relative to this file's location
_RESEARCH_DIR = pathlib.Path(__file__).parents[2] / "research"
_REPORTS_DIR  = pathlib.Path(__file__).parents[2] / "reports"

# Resolve assets/images/ directory relative to this file's location
_ASSETS_IMAGES_DIR = pathlib.Path(__file__).parents[2] / "assets" / "images"

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


_LINK_CHECK_TIMEOUT = 8  # seconds per URL
_LINK_CHECK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BeyondTomorrow-LinkChecker/1.0; "
        "+https://beyondtomorrow.world)"
    )
}

# Regex capturing all markdown links: [text](url)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


async def _check_url(client: httpx.AsyncClient, url: str) -> bool:
    """Return True if *url* is a publicly reachable https/http URL (2xx/3xx).

    Rules:
    - Must begin with http:// or https:// — bare paths, corpus refs, and
      internal identifiers are immediately rejected.
    - HEAD request first; falls back to GET if HEAD returns 405.
    - Treats 2xx and 3xx (after redirect follow) as valid.
    - Any connection error, timeout, or 4xx/5xx → invalid.
    """
    if not url.startswith(("http://", "https://")):
        return False
    try:
        resp = await client.head(url, follow_redirects=True, timeout=_LINK_CHECK_TIMEOUT)
        if resp.status_code == 405:
            resp = await client.get(url, follow_redirects=True, timeout=_LINK_CHECK_TIMEOUT)
        return resp.status_code < 400
    except Exception:
        return False


async def _validate_and_strip_links(content: str) -> str:
    """Check every markdown link in *content* and remove any that are invalid.

    A link is removed if:
    - The URL does not start with http:// or https://
    - The URL returns a 4xx/5xx status or is unreachable
    - The URL is an internal path, corpus reference, or local filename

    Removed links are converted to plain text (link label kept, URL dropped)
    and logged as warnings. Valid links are left untouched.
    """
    import logging as _log
    _ll = _log.getLogger("pipeline.tools.files")

    urls = list(dict.fromkeys(m.group(2) for m in _MD_LINK_RE.finditer(content)))
    if not urls:
        return content

    # Check all unique URLs concurrently
    async with httpx.AsyncClient(headers=_LINK_CHECK_HEADERS) as client:
        results = await asyncio.gather(*(_check_url(client, u) for u in urls))

    validity = dict(zip(urls, results))

    invalid = [u for u, ok in validity.items() if not ok]
    if invalid:
        _ll.warning("Link validation: removing %d invalid link(s): %s", len(invalid), invalid)

    def _replace(m: re.Match) -> str:
        text, url = m.group(1), m.group(2)
        if not validity.get(url, True):
            return text  # strip URL, keep label as plain text
        return m.group(0)  # leave valid links untouched

    return _MD_LINK_RE.sub(_replace, content)


def _clean_llm_text(content: str) -> str:
    """Sanitise LLM output before writing to disk.

    LLMs occasionally produce garbled punctuation in several forms:

    1. Garbled hex-encoded characters — '&' emitted as chr(0)+'26' and
       "'" as chr(0)+'27' (the hex ASCII values of each):
         \\x0026mdash;  →  &mdash;  →  — (em dash)
         \\x0027re      →  're          (contraction)

    2. ASCII SUB character (\\x1a, chr(26)) used as punctuation:
         word\\x1at     →  word't        (contraction: isn't, don't, can't)
         word\\x1as     →  word's        (possessive/contraction: it's, here's)
         word\\x1are    →  word're       (contraction: they're)
         word\\x1a word →  word, word    (clause separator → comma)

    3. Newline-split contractions (gpt-4.1-mini 413-fallback artefact):
         word\\n\\nre   →  word're       (they're, we're, you're)
         word\\n\\nt    →  word't        (don't, can't, won't)
         word\\n\\ns    →  word's        (it's, nation's, Europe's)
         word\\n\\nve   →  word've       (we've, they've)
         word\\n\\nll   →  word'll       (we'll, they'll)
         word\\n\\nd    →  word'd        (we'd, they'd)
         word\\n\\nm    →  word'm        (I'm)
       These arise when the fallback model emits a bare newline pair instead
       of an apostrophe before a contraction suffix.

    4. Orphaned fragment lines from broken em dashes (gpt-4.1-mini fallback):
       The fallback sometimes emits "word A\\n\\nword B" where an em dash was
       intended between two words/phrases that together form a single clause.
       We repair the most unambiguous case: a \\n\\n between two small words
       (≤15 chars each) where the second is a common sentence connector or
       continuation word (e.g. "the", "a", "they", "this", numeral).
       These are joined with " — " (em dash).

    5. Windows-1252 / C1 control-range smart punctuation (gpt-4.1-mini fallback):
       The fallback model sometimes emits C1 Unicode control characters (U+0080–
       U+009F) that map to Windows-1252 smart-punctuation glyphs. Ghost renders
       these as their decimal byte value (e.g. U+0092 → "92", U+0094 → "94")
       because they are invalid in HTML/XML contexts.
         \\x91  →  \u2018  (')  left single quotation mark
         \\x92s →  's          right single quote used as possessive/contraction
         \\x92  →  —           right single quote used as em-dash separator
         \\x93  →  \u201c  (") left double quotation mark
         \\x94  →  —           right double quote used as em-dash separator
         \\x96  →  –           en-dash
         \\x97  →  —           em-dash

    Also normalises typographic nuisances that break plain-text contexts:
       &nbsp; (\\xa0)   →  regular space
    """
    # 1. Restore garbled ampersands and apostrophes (LLM hex-encoding artefact)
    content = content.replace("\x0026", "&")    # chr(0)+'26' → '&'
    content = content.replace("\x0027", "'")    # chr(0)+'27' → "'"

    # 2. Unescape HTML entities → plain Unicode (&mdash; → —, &amp; → &, etc.)
    content = _html.unescape(content)

    # 3. Non-breaking space → regular space (avoids invisible layout breaks)
    content = content.replace("\xa0", " ")

    # 4. Fix \x1a (ASCII SUB) used as apostrophe in contractions (unambiguous)
    content = re.sub(r"\x1a(t|re|ve|ll|d|m)\b", r"'\1", content)
    # Also 's when immediately preceded by a letter (it's, what's, here's, etc.)
    content = re.sub(r"([A-Za-z])\x1a(s\b)", r"\1'\2", content)
    # Remaining \x1a → comma-space (used as clause/list separator)
    content = content.replace("\x1a", ", ")

    # 5. Strip any remaining null bytes
    content = content.replace("\x00", "")

    # 6. Repair newline-split contractions (gpt-4.1-mini 413-fallback artefact).
    #    Pattern: a word-ending letter immediately followed by \n\n and then a
    #    contraction suffix.  Replace with the word + apostrophe + suffix.
    content = re.sub(
        r"([A-Za-z])\n\n(re|ve|ll|d|m|t|s)\b",
        lambda m: m.group(1) + "'" + m.group(2),
        content,
    )

    # 7. Repair orphaned em-dash fragments: "word\n\nthe/a/they/..." → "word — ..."
    #    Fires when \n\n separates two tokens where the second is a short common
    #    connector, continuation word, or numeral — a reliable sign of a broken
    #    inline clause rather than a deliberate paragraph break.
    _connector = (
        r"(?:the|a|an|they|this|these|those|it|its|he|she|we|you|there|"
        r"enough|when|while|but|and|or|so|yet|not|no|never|always|both|"
        r"\d[\d,\.]*%?)"
    )
    content = re.sub(
        r"([A-Za-z][A-Za-z,]{0,14})\n\n(" + _connector + r")\b",
        r"\1 — \2",
        content,
    )

    # 8. Windows-1252 C1 control characters (U+0080–U+009F) — emitted by
    #    gpt-4.1-mini fallback. Ghost renders them as their decimal byte value
    #    (e.g. U+0092 → "92"). Fix before they reach the markdown converter.

    # \x91 / \x92 — single quotes:
    # When \x92 precedes 's' at a word boundary, it's an apostrophe.
    content = re.sub(r"([A-Za-z])\x92(s\b)", r"\1'\2", content)      # word's
    content = re.sub(r"([A-Za-z])\x92(t\b)", r"\1'\2", content)      # don't, can't
    content = re.sub(r"([A-Za-z])\x92(re|ve|ll|d|m)\b", r"\1'\2", content)  # contractions
    # Remaining \x92 between letters = em-dash (inline clause separator, no spaces)
    content = content.replace("\x91", "\u2018")   # ' left single quote
    content = content.replace("\x92", "\u2019")   # ' right single quote (any remaining)

    # \x93 / \x94 — double quotes:
    # \x94 between letters acts as em-dash (gpt-4.1-mini uses it as mdash substitute)
    content = content.replace("\x93", "\u201c")   # " left double quote
    content = content.replace("\x94", "\u201d")   # " right double quote

    # \x96 / \x97 — dashes
    content = content.replace("\x96", "\u2013")   # – en-dash
    content = content.replace("\x97", "\u2014")   # — em-dash

    return content


# ---------------------------------------------------------------------------
# Punctuation validation & auto-fix (runs after _clean_llm_text)
# ---------------------------------------------------------------------------

import logging as _logging

_file_logger = _logging.getLogger("pipeline.tools.files")


def _validate_punctuation(content: str) -> str:
    """Validate and auto-fix common punctuation errors in LLM output.

    Runs after _clean_llm_text(). Fixes what it can and logs warnings for
    issues that need manual review. Returns cleaned text.
    """
    original = content

    # 1. Collapse double spaces (except in code blocks)
    content = re.sub(r"(?<!\n)  +(?!\n)", " ", content)

    # 2. Remove space before sentence-ending punctuation
    content = re.sub(r" +([.,:;!?])", r"\1", content)

    # 3. Ensure space after punctuation when followed by a letter
    #    (skip URLs, decimal numbers, abbreviations like "e.g.", and time like "10:30")
    content = re.sub(
        r"(?<![:/\d])([.!?])([A-Z])",
        r"\1 \2",
        content,
    )

    # 4. Fix repeated punctuation (not ellipsis)
    content = re.sub(r"([,;:!?])\1+", r"\1", content)
    # Normalise any sequence of 2 or 4+ dots to proper ellipsis (3 dots)
    content = re.sub(r"(?<!\.)\.{2}(?!\.)", "...", content)
    content = re.sub(r"\.{4,}", "...", content)

    # 5. Strip orphaned HTML entities that survived _clean_llm_text unescape
    _orphaned_entities = re.findall(r"&(?:amp|mdash|ndash|nbsp|quot|ldquo|rdquo|lsquo|rsquo|#x[0-9a-fA-F]+);", content)
    if _orphaned_entities:
        _file_logger.warning("Orphaned HTML entities found (auto-fixing): %s", _orphaned_entities[:5])
        content = _html.unescape(content)

    # 6. Detect surviving C1 control characters (U+0080–U+009F)
    _c1_chars = re.findall(r"[\x80-\x9f]", content)
    if _c1_chars:
        _file_logger.warning(
            "C1 control characters survived cleanup (%d found) — "
            "replacing with spaces",
            len(_c1_chars),
        )
        content = re.sub(r"[\x80-\x9f]", " ", content)

    # 7. Fix broken markdown link syntax: [text](url without closing paren
    content = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\s*$",
        r"[\1](\2)",
        content,
        flags=re.MULTILINE,
    )

    if content != original:
        _file_logger.info("Punctuation validation applied fixes")

    return content


# ---------------------------------------------------------------------------
# British English spelling enforcement (lightweight word-boundary replacement)
# ---------------------------------------------------------------------------

# American → British spelling pairs. Only whole-word replacements to avoid
# mangling URLs, proper nouns, and technical terms.
_AMERICAN_TO_BRITISH: dict[str, str] = {
    "analyze": "analyse",
    "analyzed": "analysed",
    "analyzing": "analysing",
    "behavior": "behaviour",
    "behaviors": "behaviours",
    "center": "centre",
    "centers": "centres",
    "centered": "centred",
    "color": "colour",
    "colors": "colours",
    "colored": "coloured",
    "defense": "defence",
    "favor": "favour",
    "favored": "favoured",
    "favorable": "favourable",
    "fiber": "fibre",
    "fulfill": "fulfil",
    "gray": "grey",
    "honor": "honour",
    "honored": "honoured",
    "labor": "labour",
    "license": "licence",
    "meter": "metre",
    "meters": "metres",
    "modeling": "modelling",
    "neighbor": "neighbour",
    "neighbors": "neighbours",
    "neighborhood": "neighbourhood",
    "offense": "offence",
    "optimize": "optimise",
    "optimized": "optimised",
    "optimizing": "optimising",
    "organize": "organise",
    "organized": "organised",
    "organizing": "organising",
    "organization": "organisation",
    "organizations": "organisations",
    "practice": "practise",  # verb form only — noun is "practice" in both
    "program": "programme",
    "programs": "programmes",
    "realize": "realise",
    "realized": "realised",
    "realizing": "realising",
    "recognize": "recognise",
    "recognized": "recognised",
    "recognizing": "recognising",
    "specialize": "specialise",
    "specialized": "specialised",
    "standardize": "standardise",
    "standardized": "standardised",
    "summarize": "summarise",
    "summarized": "summarised",
    "vapor": "vapour",
}

# Pre-compile a single regex that matches any American spelling as a whole word.
# Case-insensitive matching with case-preserving replacement.
_US_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _AMERICAN_TO_BRITISH) + r")\b",
    re.IGNORECASE,
)


def _enforce_british_english(content: str) -> str:
    """Replace common American spellings with British equivalents.

    Only replaces whole words (word-boundary regex) to avoid false positives
    in URLs, proper nouns, and technical terms. Preserves original case.
    Skips content inside markdown links to avoid mangling URLs.
    """
    def _replace_match(m: re.Match) -> str:
        word = m.group(0)
        lower = word.lower()
        replacement = _AMERICAN_TO_BRITISH.get(lower, word)
        # Preserve original case
        if word[0].isupper():
            replacement = replacement[0].upper() + replacement[1:]
        if word.isupper():
            replacement = replacement.upper()
        return replacement

    # Split content: skip inside markdown link URLs but still process link text.
    # Pattern captures [text](url) — we process `text` but leave `url` intact.
    parts = re.split(r"(\[[^\]]*\]\([^)]*\))", content)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            # This is a markdown link [text](url) — process text, preserve URL
            m = re.match(r"\[([^\]]*)\]\(([^)]*)\)", part)
            if m:
                link_text = _US_PATTERN.sub(_replace_match, m.group(1))
                result.append(f"[{link_text}]({m.group(2)})")
            else:
                result.append(part)
        else:
            result.append(_US_PATTERN.sub(_replace_match, part))

    replaced = "".join(result)
    if replaced != content:
        _file_logger.info("British English spelling corrections applied")
    return replaced


def _safe_path_in(base_dir: pathlib.Path, filename: str) -> pathlib.Path:
    """Return a resolved path under base_dir, raising ValueError on traversal."""
    base_dir.mkdir(parents=True, exist_ok=True)
    resolved = (base_dir / filename).resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        raise ValueError(f"Path traversal attempt blocked: {filename}")
    return resolved


def _safe_path(filename: str) -> pathlib.Path:
    """Return a resolved path under research/ or reports/, raising ValueError on traversal.

    Strips a leading 'research/' or 'reports/' prefix that LLMs sometimes add,
    then routes to the correct base directory.  Unprefixed filenames default to
    research/.
    """
    for prefix in ("research/", "research\\"):
        if filename.lower().startswith(prefix):
            return _safe_path_in(_RESEARCH_DIR, filename[len(prefix):])
    for prefix in ("reports/", "reports\\"):
        if filename.lower().startswith(prefix):
            return _safe_path_in(_REPORTS_DIR, filename[len(prefix):])
    # No explicit prefix — default to research/
    return _safe_path_in(_RESEARCH_DIR, filename)


@function_tool
async def read_research_file(filename: str) -> str:
    """Read a file from the research/ or reports/ directory.

    Checks research/ first (respecting an explicit 'research/' prefix), then
    falls back to reports/ for unprefixed filenames not found in research/.
    Binary files such as PDFs are not readable via this tool — use the INDEX:
    pipeline command to extract and index PDF content instead.

    Args:
        filename: Name of the file to read (e.g. '2026-02-22-quantum.md' or
                  'reports/WMO-1391-2025_en.pdf').
    """
    try:
        path = _safe_path(filename)
    except ValueError as exc:
        return f"Error: {exc}"

    # If the file wasn't found and no explicit directory prefix was given,
    # also check the other directory.
    if not path.exists():
        has_prefix = any(
            filename.lower().startswith(p)
            for p in ("research/", "research\\", "reports/", "reports\\")
        )
        if not has_prefix:
            try:
                alt_path = _safe_path_in(_REPORTS_DIR, filename)
                if alt_path.exists():
                    path = alt_path
                else:
                    return f"File not found in research/ or reports/: {filename}"
            except ValueError:
                pass
        if not path.exists():
            return f"File not found: {filename}"

    if path.suffix.lower() == ".pdf":
        return (
            f"Binary PDF file — cannot read as text: {filename}. "
            "Use the pipeline INDEX: command to extract and index its content."
        )

    return path.read_text(encoding="utf-8")


@function_tool
async def write_research_file(filename: str, content: str) -> str:
    """Write content to a file in the research/ directory. Creates the file if it doesn't exist.

    Args:
        filename: Name of the file to write (e.g. '2026-02-22-quantum.md').
                  Subdirectories are created automatically.
        content: The full content to write to the file.
    """
    try:
        path = _safe_path(filename)
    except ValueError as exc:
        return f"Error: {exc}"

    path.parent.mkdir(parents=True, exist_ok=True)
    content = _clean_llm_text(content)
    content = _validate_punctuation(content)
    content = _enforce_british_english(content)

    # Validate all markdown links in edited posts before saving
    if "-edited" in filename:
        content = await _validate_and_strip_links(content)

    path.write_text(content, encoding="utf-8")

    # Log readability metrics for edited posts (the ones heading to Ghost)
    if "-edited" in filename:
        try:
            from pipeline.guardrails import score_readability
            metrics = score_readability(content)
            _file_logger.info(
                "Readability — words: %d, avg sentence: %.1f, Flesch: %.1f (%s)",
                metrics["word_count"], metrics["avg_sentence_len"],
                metrics["flesch_score"], metrics["grade_label"],
            )
            for w in metrics["warnings"]:
                _file_logger.warning("Readability: %s", w)
        except Exception:
            pass  # non-fatal

    return f"Written {len(content):,} characters to research/{filename}"


@function_tool
async def pick_random_asset_image() -> str:
    """Pick a random image file from the assets/images/ directory.

    Returns the absolute path to the selected image, or an error message
    if the directory is missing or contains no supported images.
    """
    if not _ASSETS_IMAGES_DIR.exists():
        return f"Error: assets/images/ directory not found at {_ASSETS_IMAGES_DIR}"

    images = [
        f for f in _ASSETS_IMAGES_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in _IMAGE_EXTENSIONS
    ]

    if not images:
        return "Error: No image files found in assets/images/"

    chosen = random.choice(images)
    return str(chosen)
