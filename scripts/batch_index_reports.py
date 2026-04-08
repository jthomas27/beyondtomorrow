"""Batch index all PDFs in reports/ that are not yet in the corpus.

Usage:
    .venv/bin/python scripts/batch_index_reports.py [--force]

Options:
    --force   Re-index PDFs even if they are already indexed.
"""
import asyncio
import sys
import pathlib
from datetime import date

PROJECT_ROOT = pathlib.Path(__file__).parent.parent


async def main(force: bool = False) -> None:
    # Bootstrap env + DB pool before importing pipeline tools.
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    from pipeline.db import close_pool
    from pipeline.tools.corpus import _index_document_impl, _is_source_indexed

    reports_dir = PROJECT_ROOT / "reports"
    pdfs = sorted(reports_dir.glob("*.pdf"))

    if not pdfs:
        print("No PDFs found in reports/")
        return

    today = str(date.today())
    total = len(pdfs)
    indexed_count = 0
    skipped_count = 0
    failed_count = 0

    for i, pdf_path in enumerate(pdfs, 1):
        source = f"reports/{pdf_path.name}"
        print(f"[{i}/{total}] {pdf_path.name}", end=" ... ", flush=True)

        if not force:
            try:
                already = await _is_source_indexed(source)
            except Exception as exc:
                print(f"WARN (dedup check failed: {exc}) — indexing anyway")
                already = False
            if already:
                print("SKIP (already indexed)")
                skipped_count += 1
                continue

        # Extract text from PDF.
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(pdf_path))
            pages = [page.extract_text() or "" for page in reader.pages]
            content = "\n\n".join(p for p in pages if p.strip())
        except Exception as exc:
            print(f"FAIL (PDF extraction: {exc})")
            failed_count += 1
            continue

        if not content.strip():
            print("SKIP (no extractable text)")
            skipped_count += 1
            continue

        try:
            result = await _index_document_impl(content, source, "pdf", today)
            print(f"OK — {result}")
            indexed_count += 1
        except Exception as exc:
            print(f"FAIL (indexing: {exc})")
            failed_count += 1

    await close_pool()

    print()
    print("=" * 60)
    print(f"Done.  Indexed: {indexed_count}  |  Skipped: {skipped_count}  |  Failed: {failed_count}")
    print("=" * 60)


if __name__ == "__main__":
    force = "--force" in sys.argv
    asyncio.run(main(force=force))
