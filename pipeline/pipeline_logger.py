"""pipeline/pipeline_logger.py — Structured file logging for pipeline runs.

Each pipeline run writes JSON-lines entries to logs/pipeline-YYYY-MM-DD.log.
Every entry contains: timestamp, run_id, event, stage (where applicable),
and any extra context fields (topic, model, elapsed_s, error_type, traceback).

Usage::

    from pipeline.pipeline_logger import PipelineRunLogger

    run_log = PipelineRunLogger(topic="AI safety", command="BLOG")
    run_log.stage_start("Research")
    try:
        ...
        run_log.stage_ok("Research", elapsed_s=45.2, model="gpt-4.1", tokens_in=1200)
    except Exception as exc:
        run_log.stage_error("Research", exc)
        raise
    run_log.run_complete(published_url="https://...", total_elapsed_s=300.0)
    summary = run_log.summary()  # dict for email/status replies
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any

# ---------------------------------------------------------------------------
# PostgreSQL pool (set by main.py / email_listener.py after pool is acquired)
# ---------------------------------------------------------------------------
_db_pool: Any = None

# ---------------------------------------------------------------------------
# Active run tracker — set by PipelineRunLogger.__init__, cleared on completion.
# Used by the SIGTERM handler to log run_failed before the container exits.
# ---------------------------------------------------------------------------
_active_run_log: Any = None  # PipelineRunLogger | None


def get_active_run_log() -> Any:
    """Return the currently executing PipelineRunLogger, or None."""
    return _active_run_log


def set_db_pool(pool: Any) -> None:  # noqa: ANN401  (asyncpg.Pool)
    """Register the shared asyncpg pool so _write_entry can persist logs to DB.

    Call this once after ``await get_pool()`` in each pipeline entry-point.
    Safe to call with ``None`` to disable DB writes.
    """
    global _db_pool
    _db_pool = pool


async def _write_entry_db(entry: dict) -> None:
    """Insert one log entry into the PostgreSQL pipeline_logs table.

    Silently swallows all exceptions so a DB hiccup never disrupts the pipeline.
    """
    pool = _db_pool
    if pool is None:
        return
    try:
        ts_str = entry.get("timestamp")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                ts = datetime.now(timezone.utc)
        else:
            ts = datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO pipeline_logs (run_id, event, stage, ts, data)
                VALUES ($1, $2, $3, $4, $5)
                """,
                entry.get("run_id", ""),
                entry.get("event", ""),
                entry.get("stage"),
                ts,
                json.dumps(entry, ensure_ascii=False, default=str),
            )
    except Exception as exc:  # noqa: BLE001
        _file_logger.debug("pipeline_logs DB write failed (non-fatal): %s", exc)

_LOG_DIR = Path(__file__).parent.parent / "logs"
_file_logger = logging.getLogger("pipeline.file_log")


def _format_traceback(exc: Exception) -> str:
    """Build a traceback string from the exception itself (works outside except blocks)."""
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def _format_cause_chain(exc: Exception) -> list[dict]:
    """Walk __cause__ / __context__ and return a list of {type, message} dicts."""
    chain: list[dict] = []
    seen: set[int] = set()
    current: BaseException | None = exc.__cause__ or exc.__context__
    while current and id(current) not in seen:
        seen.add(id(current))
        chain.append({"type": type(current).__name__, "message": str(current)})
        current = current.__cause__ or current.__context__
    return chain


def _env_snapshot() -> dict:
    """Capture environment context useful for diagnosing failures."""
    return {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "has_github_token": bool(os.environ.get("GITHUB_TOKEN")),
        "has_database_url": bool(os.environ.get("DATABASE_URL")),
        "has_ghost_url": bool(os.environ.get("GHOST_URL")),
        "has_ghost_admin_key": bool(os.environ.get("GHOST_ADMIN_KEY")),
        "railway": bool(os.environ.get("RAILWAY_ENVIRONMENT")),
    }


def _ensure_log_dir() -> Path:
    _LOG_DIR.mkdir(exist_ok=True)
    return _LOG_DIR


def _log_file_path() -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    return _ensure_log_dir() / f"pipeline-{today}.log"


def _write_entry(entry: dict) -> None:
    """Append a newline-delimited JSON entry to today's log file.

    Also fires a non-blocking DB insert when a pool has been registered via
    ``set_db_pool()`` and an asyncio event loop is currently running.
    The DB write is fire-and-forget — any failure is logged at DEBUG level
    only and never raises.
    """
    # --- file write (always, local debugging) ---
    try:
        with open(_log_file_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:  # noqa: BLE001
        _file_logger.warning("Could not write to pipeline log: %s", exc)

    # --- DB write (fire-and-forget when inside an async context) ---
    if _db_pool is not None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_write_entry_db(entry))
        except RuntimeError:
            pass  # No running event loop — skip DB write


class PipelineRunLogger:
    """Tracks stage statuses for one pipeline run and writes structured log entries.

    Stage methods use upsert semantics: repeated calls for the same stage name
    update the stage record so ``summary()`` always reflects the final state.
    Every call also appends a timestamped JSON event to the log file, preserving
    the full history for debugging.
    """

    def __init__(self, topic: str, command: str = "BLOG") -> None:
        global _active_run_log
        self.run_id: str = uuid.uuid4().hex[:12]
        self.topic: str = topic
        self.command: str = command
        self.started_at: datetime = datetime.now(timezone.utc)
        self._pipeline_t0: float = monotonic()
        self.stages: list[dict] = []
        self._stage_starts: dict[str, float] = {}
        _active_run_log = self

        _write_entry({
            "timestamp": self.started_at.isoformat(),
            "run_id": self.run_id,
            "event": "run_start",
            "command": command,
            "topic": topic,
            "env": _env_snapshot(),
        })

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ts(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _upsert_stage(self, record: dict) -> None:
        """Insert or replace the stage record (keyed by stage name)."""
        for i, s in enumerate(self.stages):
            if s["stage"] == record["stage"]:
                self.stages[i] = record
                return
        self.stages.append(record)

    def _elapsed(self, stage: str) -> float:
        start = self._stage_starts.get(stage)
        if start is None:
            _file_logger.warning("stage_start() was never called for '%s' — elapsed will be -1", stage)
            return -1.0
        return round(monotonic() - start, 1)

    # ------------------------------------------------------------------
    # Stage lifecycle
    # ------------------------------------------------------------------

    def stage_start(self, stage: str) -> None:
        """Record the start of a pipeline stage."""
        self._stage_starts[stage] = monotonic()
        _write_entry({
            "timestamp": self._ts(),
            "run_id": self.run_id,
            "event": "stage_start",
            "stage": stage,
        })

    def stage_ok(self, stage: str, **kwargs: Any) -> None:
        """Mark a stage as successfully completed."""
        elapsed = self._elapsed(stage)
        record: dict = {"stage": stage, "status": "ok", "elapsed_s": elapsed, **kwargs}
        self._upsert_stage(record)
        _write_entry({
            "timestamp": self._ts(),
            "run_id": self.run_id,
            "event": "stage_ok",
            **record,
        })

    def stage_error(self, stage: str, exc: Exception, **kwargs: Any) -> None:
        """Mark a stage as failed with exception details, traceback, and cause chain."""
        elapsed = self._elapsed(stage)
        tb = _format_traceback(exc)
        cause_chain = _format_cause_chain(exc)
        record: dict = {
            "stage": stage,
            "status": "error",
            "elapsed_s": elapsed,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            **kwargs,
        }
        if cause_chain:
            record["cause_chain"] = cause_chain
        self._upsert_stage(record)
        _write_entry({
            "timestamp": self._ts(),
            "run_id": self.run_id,
            "event": "stage_error",
            **record,
            "traceback": tb,
        })

    def stage_skipped(self, stage: str, reason: str) -> None:
        """Mark a stage as intentionally skipped (e.g. draft already exists)."""
        record: dict = {"stage": stage, "status": "skipped", "reason": reason}
        self._upsert_stage(record)
        _write_entry({
            "timestamp": self._ts(),
            "run_id": self.run_id,
            "event": "stage_skipped",
            **record,
        })

    # ------------------------------------------------------------------
    # Run-level events
    # ------------------------------------------------------------------

    def run_complete(self, published_url: str = "", total_elapsed_s: float = 0.0) -> None:
        """Log successful pipeline completion."""
        global _active_run_log
        _active_run_log = None
        _write_entry({
            "timestamp": self._ts(),
            "run_id": self.run_id,
            "event": "run_complete",
            "published_url": published_url,
            "total_elapsed_s": round(total_elapsed_s, 1),
        })

    def run_failed(self, failed_stage: str, exc: Exception, total_elapsed_s: float = 0.0) -> None:
        """Log pipeline failure with full traceback and cause chain."""
        global _active_run_log
        _active_run_log = None
        tb = _format_traceback(exc)
        cause_chain = _format_cause_chain(exc)
        entry: dict = {
            "timestamp": self._ts(),
            "run_id": self.run_id,
            "event": "run_failed",
            "failed_stage": failed_stage,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "total_elapsed_s": round(total_elapsed_s, 1),
            "traceback": tb,
        }
        if cause_chain:
            entry["cause_chain"] = cause_chain
        _write_entry(entry)

    def warning(self, stage: str, message: str, **kwargs: Any) -> None:
        """Log a non-fatal warning during a stage (e.g. fallback used)."""
        _write_entry({
            "timestamp": self._ts(),
            "run_id": self.run_id,
            "event": "stage_warning",
            "stage": stage,
            "message": message,
            **kwargs,
        })

    def model_fallback(
        self,
        stage: str,
        agent_name: str,
        from_model: str,
        to_model: str,
        attempt: int,
        reason: str = "",
    ) -> None:
        """Log a model switch during a stage (rate-limit fallback or proactive)."""
        _write_entry({
            "timestamp": self._ts(),
            "run_id": self.run_id,
            "event": "model_fallback",
            "stage": stage,
            "agent": agent_name,
            "from_model": from_model,
            "to_model": to_model,
            "attempt": attempt,
            "reason": reason,
        })

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Return a structured summary for email replies and status reporting.

        Returns::

            {
                "run_id":          str,
                "topic":           str,
                "command":         str,
                "started_at":      str (ISO 8601),
                "total_elapsed_s": float,
                "stages":          [{stage, status, elapsed_s, ...}],
                "failed_stage":    str | None,
                "error_message":   str | None,
                "error_type":      str | None,
                "cause_chain":     [{type, message}] | None,
                "log_file":        str,
            }
        """
        failed = [s for s in self.stages if s["status"] == "error"]
        return {
            "run_id": self.run_id,
            "topic": self.topic,
            "command": self.command,
            "started_at": self.started_at.isoformat(),
            "total_elapsed_s": round(monotonic() - self._pipeline_t0, 1),
            "stages": list(self.stages),
            "failed_stage": failed[-1]["stage"] if failed else None,
            "error_message": failed[-1]["error_message"] if failed else None,
            "error_type": failed[-1]["error_type"] if failed else None,
            "cause_chain": failed[-1].get("cause_chain") if failed else None,
            "log_file": str(_log_file_path()),
        }
