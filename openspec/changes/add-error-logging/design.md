# Design

## Context

Two entry points run the same pipeline: `run.py` (CLI, judged runs) and `app.py` (Flask demo with background worker threads). Today there is no logging at all — model provider failures are retried silently in `BaseAgent.call_llm` ([agents/base.py:49-67](../../../agents/base.py)) and surface only as the final exception; the CLI prints one stderr line ([run.py:30-32](../../../run.py)) and the web worker stores the exception on the job dict for API responses ([app.py:251-255](../../../app.py)). See proposal.md for motivation.

Constraints: stdlib-only (no new dependencies); both entry points must share one setup; the Flask demo may run under `debug=True` without the reloader, and imports happen once per process; web runs are multi-threaded (one daemon thread per job) so log lines from concurrent jobs must stay attributable.

## Goals / Non-Goals

**Goals:**
- Every failure — provider call attempts, final provider failures, pipeline exceptions at both entry points — lands in a persistent file and on the console with enough detail to diagnose (attempt count, status code, traceback).
- Job-id correlation for web runs so a log line can be matched to an API job.
- Lifecycle INFO records (start / done / export / validation) so a run is reconstructable from the log alone.

**Non-Goals:**
- Structured/JSON logs or log shipping (no external sinks).
- Changes to retry policy, API payloads, audit.json format, or the trace collector (the `_trace` in audit output already records per-step data; this change does not touch it).
- Per-request HTTP middleware logging of every request/response.

## Decisions

### 1. Stdlib `logging` with a single idempotent `setup_logging()` in `core/logging_setup.py`

A new module exposes `setup_logging(log_dir=None, level=INFO)` that configures the root logger once: a `StreamHandler` (console) and a `RotatingFileHandler` at `logs/clearanswer.log` (1 MB × 3 backups). Idempotency: a module-level flag plus a check that the file handler is already attached, so double calls (reloader, tests importing both entry points) never duplicate records.

Alternatives considered:
- `logging.basicConfig()` inline in each entry point — rejected: no rotation, and two call sites would drift.
- Third-party logger (loguru/structlog) — rejected: new dependency for a hackathon demo; stdlib covers everything needed.

`run.py` calls it at the top of `main()`; `app.py` calls it at import time next to `load_dotenv()`, so both the `__main__` path and any WSGI/test import get logging.

### 2. Log provider failures inside `BaseAgent.call_llm`'s existing except branch

In the retry loop's `except`: log a WARNING per failed attempt — `attempt {n}/{MAX_RETRIES+1}`, error class name, `status_code` when present (via the same `getattr` used by `_is_transient`). On the final `raise`, first log ERROR with `exc_info=True`. No change to retry counts, backoff, or which errors are considered transient.

Alternative: a decorator/interceptor wrapping `client.messages.create` — rejected: the except branch already has the attempt context; a wrapper would obscure it.

### 3. Job correlation via `extra={"job_id": ...}` + formatter fallback

The web worker logs with `extra={"job_id": job_id}`. A small custom `Formatter` appends `[job=<id>]` to the message when the record carries that attribute; records without it log normally. Chosen over `LoggerAdapter` (more machinery for one field) and over embedding the id in every message string (easy to forget).

CLI runs log with an `extra` carrying the report path instead, so CLI lines are attributable too.

### 4. Secret redaction in the formatter

The custom formatter also scrubs the configured API key value (`config.ANTHROPIC_API_KEY`) from the final formatted line before emitting — a cheap `str.replace` guard against tracebacks or error messages that embed it. This satisfies the "no secrets" requirement without parsing log content elsewhere.

### 5. Log levels

- DEBUG: retry sleep / backoff details (logged but below default threshold).
- INFO: lifecycle events (audit start/done, export written, validator pass/fail).
- WARNING: each failed provider attempt; validator failure fallback.
- ERROR: final provider failure (with traceback), pipeline exceptions at both entry points.

Both handlers use the same level (INFO); raising the console to WARNING is a one-line change later if needed.

## Risks / Trade-offs

- **Log file growth on long demos** → bounded by rotation (1 MB × 3 ≈ 4 MB max).
- **Tracebacks containing secrets** → formatter-level redaction of the known key value; other secrets are not expected in tracebacks (keys come from env, not request data).
- **Concurrent jobs interleaving lines** → `logging` is thread-safe per record; job-id suffix keeps multi-line tracebacks attributable.
- **Flask's own logging** → root-logger handlers also capture Flask/Werkzeug records (request lines), which is desirable; no extra middleware needed.
- **Windows path/locking of the log file while the app runs** → rotation uses `delay`/default behavior; worst case a rotate fails and the current file keeps being written (handler swallows OSError), acceptable for a demo.

## Migration Plan

Purely additive: deploy by restarting the CLI/web process after the code lands. No data migration, no API changes. Rollback = revert the code; the `logs/` directory is inert without it and is added to `.gitignore`.

## Open Questions

- Exact rotation size/backup count (1 MB × 3 chosen as default) — tunable in config later without touching behavior.
- Whether to add a `LOG_LEVEL` env var override — trivial to add if wanted; not required by the spec.
