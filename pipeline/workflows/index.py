"""Index workflow implementation."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from time import monotonic

from pipeline.paths import PROJECT_ROOT
from pipeline.workflows.common import _AGENT_TIMEOUT, _STAGE_COOLDOWN, _RETRY_BACKOFF_BASE

logger = logging.getLogger("pipeline")



async def _run_index(task: str) -> dict:
    """Handle INDEX: path — extract text, check dedup, index to corpus.

    Supports files in research/, reports/, or any path relative to the project root.
    PDFs are extracted via pypdf.  Files already present in the corpus are skipped.
    """
    import pathlib
    from datetime import date
    from pipeline.tools.corpus import _index_document_impl, _is_source_indexed
    from pipeline.db import close_pool
    from pipeline.setup import init_openai

    init_openai()

    raw_path = task[len("INDEX:"):].strip()
    project_root = PROJECT_ROOT
    file_path = (project_root / raw_path).resolve()

    if not file_path.exists():
        print(f"File not found: {raw_path}")
        await close_pool()
        return {"status": "failed"}

    # Use the normalised relative path as the dedup source key.
    try:
        source = str(file_path.relative_to(project_root))
    except ValueError:
        source = raw_path

    try:
        already_indexed = await _is_source_indexed(source)
    except Exception as exc:
        logger.warning("Could not check dedup status: %s", exc)
        already_indexed = False

    if already_indexed:
        print(f"Already indexed — skipping: {source}")
        await close_pool()
        return {"status": "complete"}

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(file_path))
            pages = [page.extract_text() or "" for page in reader.pages]
            content = "\n\n".join(p for p in pages if p.strip())
        except Exception as exc:
            print(f"PDF extraction failed for {raw_path}: {exc}")
            await close_pool()
            return {"status": "failed"}
    else:
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"Could not read {raw_path}: {exc}")
            await close_pool()
            return {"status": "failed"}

    if not content.strip():
        print(f"No extractable content in: {raw_path}")
        await close_pool()
        return {"status": "failed"}

    doc_type = "pdf" if suffix == ".pdf" else "article"
    doc_date = str(date.today())

    logger.info("Indexing %s (%s chars)...", source, len(content))
    try:
        result = await _index_document_impl(content, source, doc_type, doc_date)
        print(result)
        return {"status": "failed" if str(result).startswith("Error:") else "complete"}
    except Exception as exc:
        print(f"Indexing failed: {exc}")
        return {"status": "failed"}
    finally:
        await close_pool()
