# Proposal

## Why

The system has no persistent failure record. Model provider failures in `BaseAgent.call_llm` are retried silently and surface only as the final exception — one line on CLI stderr or a job-dict field in the web API — with no per-attempt detail, no traceback at the source of the failure, and nothing written to disk. When an audit fails (provider outage, rate limit exhaustion, missing API key), there is no log to diagnose it from; the only evidence is whatever the UI or terminal happened to show.

## What Changes

- Introduce a single centralized logging setup (stdlib `logging`) shared by both entry points (CLI `run.py` and web `app.py`): console output plus a rotating file under `logs/`.
- Log every model provider failure at the point it occurs: each retry attempt (attempt number, error type, HTTP status when present) and the final failure with its traceback.
- Log pipeline-level failures in the CLI entry point and the web background worker, including the job id for correlation with API responses.
- Log key lifecycle events (audit start/finish, export written, validator pass/fail) so a log line sequence tells the story of a run even when nothing failed.
- Existing behavior is unchanged: CLI stderr messages, API error payloads, and job state transitions all stay as they are — logging is purely additive.

## Capabilities

### New Capabilities

- `error-logging`: centralized failure and lifecycle logging for the audit pipeline, covering model provider call failures, pipeline-level exceptions, and run lifecycle events across both the CLI and web entry points.

### Modified Capabilities

(none — existing specs' requirements are unchanged; this is additive observability)

## Impact

- **Code**: a new small logging-setup module (e.g. `core/logging_setup.py`); targeted edits to `agents/base.py` (attempt/failure logging in `call_llm`), `run.py` (CLI failure + lifecycle logging), and `app.py` (worker failure + job-corrrelated lifecycle logging).
- **New artifact**: log file under `logs/` (added to `.gitignore`).
- **APIs / contracts**: none — no endpoint, payload, or audit.json format changes.
- **Dependencies**: none — stdlib `logging` and `logging.handlers.RotatingFileHandler` only.
