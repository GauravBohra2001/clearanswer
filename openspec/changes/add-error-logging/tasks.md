# Tasks

## 1. Central logging setup

- [x] 1.1 Create `core/logging_setup.py` with an idempotent `setup_logging()`: root logger at INFO, console `StreamHandler` plus `RotatingFileHandler` for `logs/clearanswer.log` (1 MB × 3 backups), and a custom `Formatter` that appends `[job=<id>]` or `[run=<path>]` when the record carries that `extra` field and redacts the configured API key value from every formatted line. Verify with a test in `core/tests/test_logging_setup.py`: calling `setup_logging()` twice emits each record exactly once per handler, and a log message containing a fake key value is redacted in the output file.
- [x] 1.2 Add `logs/` to `.gitignore`. Verify with `git check-ignore logs/clearanswer.log` returning the path.

## 2. Model provider failure logging

- [x] 2.1 In `BaseAgent.call_llm`'s retry loop, log a WARNING per failed attempt (attempt number over `MAX_RETRIES + 1`, error class name, HTTP status code when present via the same `getattr` used by `_is_transient`) and, before the final `raise`, log an ERROR with `exc_info=True`. Do not change retry counts, backoff, or transient classification. Verify with a test in `core/tests/test_call_llm_logging.py` using a stubbed client: a call that raises a 429-style error twice then succeeds logs two WARNINGs; a call that always fails (or hits a non-transient 401) logs one ERROR record containing the traceback and still raises the original exception type.
- [x] 2.2 Run the existing suite (`python test_foundation.py` and `core/tests/`) to confirm no regressions from the `call_llm` change. Verify both pass exactly as before.

## 3. Entry-point logging

- [x] 3.1 In `run.py`: call `setup_logging()` at the top of `main()`; log INFO on audit start (report path) and completion (finding count); in the existing `except`, log ERROR with `exc_info=True` and the report path as `extra` before printing the stderr line (stderr behavior unchanged). Verify by running the CLI against a nonexistent data dir: the stderr message still prints, exit code is 1, and `logs/clearanswer.log` contains an ERROR record with traceback.
- [x] 3.2 In `app.py`: call `setup_logging()` at import time next to `load_dotenv()`; in `_run_audit_job`, log INFO on start (with `job_id` extra) and completion (finding count), and in the existing `except` log ERROR with `exc_info=True` and `job_id` extra before storing the error on the job dict (job-dict behavior unchanged). Verify by POSTing a report to `/api/audit` with a failing configuration (e.g. unset API key): the log file contains an ERROR record tagged `[job=<id>]`, and `GET /api/status/<job_id>` still returns state `error` with the stored error string.
- [x] 3.3 In `app.py`'s export path: log INFO when the submission file is written (output path) and the validator outcome — INFO on pass, WARNING on fail. Verify by exporting a completed job: the log shows the write path followed by the validator result line, and the API response is unchanged.

## 4. End-to-end verification

- [ ] 4.1 Run one full successful audit via CLI and one via the web API (submit → poll → export). Verify in `logs/clearanswer.log`: lifecycle records appear in chronological order (start → done with finding count → export path → validator outcome), no log record anywhere contains the configured API key value (`grep` for it returns nothing), and existing outputs are unchanged (validation still OK, status/result payloads identical in shape).
