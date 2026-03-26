"""
pipeline/reports_watcher.py — Automatic indexing of new files in reports/

Monitors the reports/ folder and indexes any file not already in the vector
database.  Runs two complementary mechanisms:

    1. Startup scan  — indexes every existing file in reports/ that is not yet
                       in the corpus.  Safe to call repeatedly (dedup check
                       via _is_source_indexed prevents re-indexing).

    2. Watchdog watch — filesystem event handler that indexes new files the
                        moment they appear.  Uses the platform-native backend
                        (FSEvents on macOS, inotify on Linux); falls back to
                        the polling observer when native events are unavailable.

Supported file types: .pdf, .txt, .md, .json

Usage (standalone):
    python -m pipeline.reports_watcher

The watcher logs progress to the ``pipeline.reports_watcher`` logger.  It
never raises; all errors are logged and swallowed so the daemon keeps running.
"""

import asyncio
import logging
import pathlib

logger = logging.getLogger("pipeline.reports_watcher")

_REPORTS_DIR = pathlib.Path(__file__).parent.parent / "reports"

_SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".json"}


# ---------------------------------------------------------------------------
# Text-extraction helpers
# ---------------------------------------------------------------------------

def _extract_text(file_path: pathlib.Path) -> str:
    """Return the plain-text content of *file_path*, or '' on failure."""
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(file_path))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(p for p in pages if p.strip())
        except Exception as exc:
            logger.error("PDF extraction failed for %s: %s", file_path.name, exc)
            return ""

    if suffix in {".txt", ".md", ".json"}:
        try:
            return file_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("Could not read %s: %s", file_path.name, exc)
            return ""

    return ""


def _doc_type(file_path: pathlib.Path) -> str:
    mapping = {".pdf": "pdf", ".txt": "article", ".md": "article", ".json": "research"}
    return mapping.get(file_path.suffix.lower(), "article")


# ---------------------------------------------------------------------------
# Core indexing helper (sync wrapper around the async implementation)
# ---------------------------------------------------------------------------

async def _index_file_async(file_path: pathlib.Path) -> None:
    """Extract text from *file_path* and store it in the corpus if not already present.

    Writes a structured JSON-lines entry to the daily pipeline log for every
    outcome (skipped, indexed, error) so the full history is traceable.

    Storage layout (per _index_document_impl):
        documents row  — full extracted text + source metadata
        chunks rows    — overlapping word-boundary segments (max ~200 words each)
        embeddings rows — 384-dim all-MiniLM-L6-v2 vector per chunk + JSONB metadata
    """
    import traceback as _tb
    from datetime import date, datetime, timezone
    from time import monotonic
    from pipeline.tools.corpus import _index_document_impl, _is_source_indexed
    from pipeline.pipeline_logger import _write_entry

    project_root = pathlib.Path(__file__).parent.parent
    try:
        source = str(file_path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        source = str(file_path)

    ts = datetime.now(timezone.utc).isoformat()
    file_size = file_path.stat().st_size if file_path.exists() else 0

    try:
        already = await _is_source_indexed(source)
    except Exception as exc:
        logger.warning("Dedup check failed for %s: %s", source, exc)
        already = False

    if already:
        logger.debug("Already indexed — skipping: %s", source)
        _write_entry({
            "timestamp": ts,
            "event": "report_skipped",
            "reason": "already_indexed",
            "source": source,
            "file_name": file_path.name,
            "doc_type": _doc_type(file_path),
            "file_size_bytes": file_size,
        })
        return

    content = _extract_text(file_path)
    if not content.strip():
        logger.warning("No extractable content — skipping: %s", source)
        _write_entry({
            "timestamp": ts,
            "event": "report_skipped",
            "reason": "no_extractable_content",
            "source": source,
            "file_name": file_path.name,
            "doc_type": _doc_type(file_path),
            "file_size_bytes": file_size,
        })
        return

    doc_type = _doc_type(file_path)
    doc_date = str(date.today())
    char_count = len(content)

    _write_entry({
        "timestamp": ts,
        "event": "report_index_start",
        "source": source,
        "file_name": file_path.name,
        "doc_type": doc_type,
        "file_size_bytes": file_size,
        "char_count": char_count,
        "date": doc_date,
    })

    logger.info("Indexing %s (%d chars, %d bytes)…", source, char_count, file_size)
    t0 = monotonic()
    try:
        result = await _index_document_impl(content, source, doc_type, doc_date)
        elapsed = round(monotonic() - t0, 1)

        # Parse chunk count from the return string ("Indexed N chunks from …")
        chunk_count: int | None = None
        try:
            chunk_count = int(result.split("Indexed")[1].split("chunks")[0].strip())
        except Exception:
            pass

        logger.info("%s (%.1fs)", result, elapsed)
        _write_entry({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "report_indexed",
            "source": source,
            "file_name": file_path.name,
            "doc_type": doc_type,
            "file_size_bytes": file_size,
            "char_count": char_count,
            "chunk_count": chunk_count,
            "elapsed_s": elapsed,
            "date": doc_date,
            "result": result,
        })
    except Exception as exc:
        elapsed = round(monotonic() - t0, 1)
        tb_str = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
        logger.error("Indexing failed for %s: %s", source, exc)
        _write_entry({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "report_index_error",
            "source": source,
            "file_name": file_path.name,
            "doc_type": doc_type,
            "file_size_bytes": file_size,
            "char_count": char_count,
            "elapsed_s": elapsed,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": tb_str,
        })


# ---------------------------------------------------------------------------
# Startup scan
# ---------------------------------------------------------------------------

async def scan_and_index_new_reports() -> int:
    """Scan reports/ and index any file not yet in the corpus.

    Delegates dedup checking and logging to _index_file_async so every file
    gets a log entry regardless of outcome (indexed, skipped, or error).
    Returns the number of files newly indexed.
    """
    if not _REPORTS_DIR.exists():
        logger.debug("reports/ directory does not exist — nothing to scan.")
        return 0

    candidates = [
        f for f in _REPORTS_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTENSIONS
    ]

    if not candidates:
        logger.debug("reports/ contains no supported files.")
        return 0

    logger.info("Scanning reports/ — %d candidate file(s) found.", len(candidates))

    indexed = 0
    for file_path in sorted(candidates):
        from pipeline.tools.corpus import _is_source_indexed
        project_root = pathlib.Path(__file__).parent.parent
        try:
            source = str(file_path.resolve().relative_to(project_root.resolve()))
        except ValueError:
            source = str(file_path)
        try:
            already = await _is_source_indexed(source)
        except Exception:
            already = False

        # Always call _index_file_async — it owns dedup checking and log writing.
        await _index_file_async(file_path)
        if not already:
            indexed += 1

    logger.info("Scan complete — %d new file(s) indexed.", indexed)
    return indexed


# ---------------------------------------------------------------------------
# Watchdog event handler
# ---------------------------------------------------------------------------

def _make_event_handler():
    """Return a watchdog FileSystemEventHandler that indexes new/moved-in files."""
    try:
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        return None

    class _ReportsHandler(FileSystemEventHandler):
        def _handle(self, path: str) -> None:
            fp = pathlib.Path(path)
            if fp.suffix.lower() not in _SUPPORTED_EXTENSIONS:
                return
            if not fp.is_file():
                return
            logger.info("New file detected in reports/: %s", fp.name)
            # Run the async indexer from the synchronous watchdog callback.
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(_index_file_async(fp))
                else:
                    loop.run_until_complete(_index_file_async(fp))
            except RuntimeError:
                # No event loop in this thread — create a fresh one.
                asyncio.run(_index_file_async(fp))

        def on_created(self, event):
            if not event.is_directory:
                self._handle(event.src_path)

        def on_moved(self, event):
            # A file moved into reports/ (e.g. from a temp/partial write).
            if not event.is_directory:
                self._handle(event.dest_path)

    return _ReportsHandler()


# ---------------------------------------------------------------------------
# Main watch loop
# ---------------------------------------------------------------------------

async def run_watcher() -> None:
    """Start the reports/ watcher: startup scan + watchdog monitor."""
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Index any files already present.
    await scan_and_index_new_reports()

    # 2. Start watchdog for real-time detection.
    try:
        from watchdog.observers import Observer
    except ImportError:
        logger.warning(
            "watchdog not installed — real-time monitoring disabled. "
            "Run `pip install watchdog` to enable it."
        )
        return

    handler = _make_event_handler()
    if handler is None:
        return

    observer = Observer()
    observer.schedule(handler, str(_REPORTS_DIR), recursive=False)
    observer.start()
    logger.info("Watching %s for new reports…", _REPORTS_DIR)

    try:
        while True:
            await asyncio.sleep(1)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        observer.stop()
        observer.join()
        logger.info("Reports watcher stopped.")


# ---------------------------------------------------------------------------
# Standalone entry point:  python -m pipeline.reports_watcher
# ---------------------------------------------------------------------------

def _load_dotenv() -> None:
    from pathlib import Path
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.is_file():
        return
    import os
    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        stream=sys.stdout,
    )
    _load_dotenv()
    asyncio.run(run_watcher())
