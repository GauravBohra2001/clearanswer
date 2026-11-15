"""Centralized, idempotent logging setup shared by the CLI and web entry points.

Configures the root logger once per process with two handlers — a console
StreamHandler and a RotatingFileHandler under ``logs/`` — plus a formatter
that (a) appends a ``[job=<id>]`` or ``[run=<path>]`` tag when the record
carries that extra field, and (b) redacts the configured API key value from
every formatted line so tracebacks never leak it.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import config

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE_NAME = "clearanswer.log"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3

_configured = False


class _ContextFormatter(logging.Formatter):
    """Base formatter with job/run tagging and API-key redaction."""

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        job_id = getattr(record, "job_id", None)
        run_path = getattr(record, "run_path", None)
        if job_id is not None:
            line += f" [job={job_id}]"
        elif run_path is not None:
            line += f" [run={run_path}]"
        key = config.ANTHROPIC_API_KEY
        if key:
            line = line.replace(key, "[REDACTED]")
        return line


def setup_logging(log_dir: str | Path | None = None, level: int = logging.INFO) -> None:
    """Configure root-logger console + rotating file output.

    Idempotent: a module-level flag plus a check that the file handler is
    already attached means calling this twice in one process never duplicates
    handlers or records.
    """
    global _configured
    root = logging.getLogger()
    log_path = Path(log_dir or LOG_DIR) / LOG_FILE_NAME

    if _configured:
        return
    already_attached = any(
        isinstance(h, RotatingFileHandler) and Path(getattr(h, "baseFilename", "")) == log_path
        for h in root.handlers
    )
    if already_attached:
        _configured = True
        return

    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = _ContextFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    console_handler = logging.StreamHandler()
    for handler in (console_handler, file_handler):
        handler.setLevel(level)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(level)
    _configured = True
