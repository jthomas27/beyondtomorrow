# Report Indexer

Automatically indexes files dropped into the `reports/` folder into the pgvector knowledge corpus, making them searchable by all pipeline agents.

---

## Overview

The indexer runs two complementary mechanisms:

1. **Startup scan** — checks every file in `reports/` on boot and indexes anything not yet in the corpus
2. **Watchdog monitor** — listens for new files in real time and indexes them the moment they appear

Both paths share the same indexing logic and write structured log entries for every outcome.

---

## Workflow

```
reports/ folder
      │
      ├── Startup scan (on boot / every poll cycle)
      │         │
      │         └── For each file → check dedup → extract text → chunk → embed → store
      │
      └── Watchdog (real-time, file created or moved in)
                │
                └── New file detected → extract text → chunk → embed → store
```

### Step-by-step

**1. File detection**
- Startup scan: iterates all files in `reports/` on process start (and on every email listener poll cycle, ~every 5 min on Railway)
- Watchdog: uses platform-native filesystem events (FSEvents on macOS, inotify on Linux) to detect new files instantly — no polling delay

**2. Dedup check**
- Queries `SELECT id FROM documents WHERE source = $1` using the file's normalised relative path as the unique key (e.g. `reports/WMO-1391-2025_en.pdf`)
- If the source already exists → write a `report_skipped` log entry and stop
- Safe to re-run at any time — already-indexed files are never re-processed

**3. Text extraction**
- `.pdf` — extracted page-by-page using `pypdf`; blank pages skipped
- `.txt` / `.md` / `.json` — read as UTF-8 text directly
- If extraction yields no content → write a `report_skipped` log entry and stop

**4. Storage**
Three database writes happen in a single transaction:

| Table | What is stored |
|---|---|
| `documents` | Full extracted text, source path, doc type, date — upserted on `source` key |
| `chunks` | Overlapping word-boundary segments (~350 words each, 35-word overlap) |
| `embeddings` | 384-dim vector per chunk (BAAI/bge-small-en-v1.5) + JSONB metadata |

The full text is always stored in `documents.content`. Chunks and embeddings are rebuilt from scratch on re-index (old rows deleted first).

**5. Logging**
Every outcome writes a JSON-lines entry to `logs/pipeline-YYYY-MM-DD.log`:

| Event | When |
|---|---|
| `report_index_start` | Extraction complete, about to write to DB |
| `report_indexed` | Successfully stored — includes `chunk_count`, `char_count`, `elapsed_s` |
| `report_skipped` | Already indexed or no extractable content — includes `reason` |
| `report_index_error` | DB write failed — includes `error_type`, `error_message`, full `traceback` |

---

## Supported File Types

| Extension | Doc type | Extraction method |
|---|---|---|
| `.pdf` | `pdf` | pypdf (page-by-page) |
| `.txt` | `article` | UTF-8 text read |
| `.md` | `article` | UTF-8 text read |
| `.json` | `research` | UTF-8 text read |

---

## Integration Points

- **Email listener** (`pipeline/email_listener.py`) — calls `scan_and_index_new_reports()` at startup and on every poll cycle so Railway deployments pick up new files without a watchdog
- **`INDEX:` CLI command** — `pipeline/main.py` handles `INDEX: reports/<filename>` directly with the same dedup + PDF extraction logic
- **Agent search** — indexed content is immediately available to `search_corpus` in all agents (Researcher, Editor, etc.)

---

## Running

```bash
# Standalone watcher — startup scan + real-time monitoring
.venv/bin/python -m pipeline.reports_watcher

# One-off index of a single file via the pipeline CLI
.venv/bin/python -m pipeline.main "INDEX: reports/my-report.pdf"
```

---

## Files

| File | Role |
|---|---|
| `pipeline/reports_watcher.py` | Startup scan, watchdog handler, `_index_file_async` |
| `pipeline/tools/corpus.py` | `_index_document_impl` (chunk → embed → store), `_is_source_indexed` (dedup) |
| `pipeline/pipeline_logger.py` | `_write_entry` (JSON-lines log writer) |
| `reports/` | Drop folder — any supported file placed here is auto-indexed |
| `logs/pipeline-YYYY-MM-DD.log` | Daily structured log — one JSON entry per indexing event |
