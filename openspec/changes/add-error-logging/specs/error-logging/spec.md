# Spec Delta

## Purpose

Give every run of the Research Claim Auditor a persistent, diagnostic log: any failure — especially model provider failures — and key lifecycle events are recorded to both the console and a log file, so a failed or slow run can be diagnosed after the fact.

## ADDED Requirements

### Requirement: Centralized log output for both entry points
The system SHALL configure process-wide logging once per process for both the CLI entry point (run.py) and the web entry point (app.py), writing every record to both the console and a rotating log file under a `logs/` directory at the project root. Re-initializing logging within a process SHALL NOT duplicate handlers or records.

#### Scenario: A completed run leaves a log file
- **WHEN** an audit finishes via either the CLI or the web API
- **THEN** the same log records are present in the console output and in a file under `logs/`

#### Scenario: No duplicated records on re-init
- **WHEN** logging setup is invoked more than once in the same process (for example by a server reloader)
- **THEN** each event still appears exactly once per handler

### Requirement: Model provider failures logged at the point of failure
The system SHALL log every failed model provider call attempt as it occurs, recording the attempt number, the error type, and the HTTP status code when the error carries one. When a call ultimately fails (retries exhausted on a transient error, or any non-transient error), the system SHALL log an error-level record with the full traceback before the exception propagates. Retry behavior itself is unchanged.

#### Scenario: Transient failure logged before retry
- **WHEN** a provider call fails with a transient status such as 429 or 503
- **THEN** a warning-level record records the attempt number, error type, and status code before the next retry is attempted

#### Scenario: Final failure logged with traceback
- **WHEN** all retries are exhausted, or a non-transient error (for example 401 bad key) occurs
- **THEN** an error-level record with the full traceback is written to the log before the exception propagates to the caller

### Requirement: Pipeline failures logged at both entry points
The system SHALL log unhandled pipeline exceptions as error-level records with tracebacks in both the CLI entry point and the web background worker. For web jobs, the record SHALL include the job id so log lines can be correlated with API responses. Existing failure surfacing is unchanged: the CLI still prints its stderr message and the web job still records the exception on the job dict for status/result endpoints.

#### Scenario: Web worker failure logged with job id
- **WHEN** the orchestrator raises inside a background audit worker
- **THEN** an error-level record containing the job id and traceback is written, and the job state becomes "error" as before

#### Scenario: CLI failure logged
- **WHEN** the orchestrator raises during a CLI run
- **THEN** an error-level record with the traceback is written to the log file and the stderr message is still printed

### Requirement: Run lifecycle events logged
The system SHALL emit info-level records for key lifecycle events of a run: audit start (identifying the job id or report path), audit completion (with the number of findings), export write (with the output path), and validator outcome (pass or fail). These records SHALL appear in chronological order so the log alone tells the story of a run.

#### Scenario: Full lifecycle visible in one log
- **WHEN** a web audit runs from submission to export
- **THEN** the log contains, in order: start, completion with finding count, export write path, and validator outcome

### Requirement: Log records contain no secrets or full payloads
Log records SHALL NOT contain the Anthropic API key, and SHALL NOT embed full report text or full model request/response bodies. Failure records MAY include error messages and tracebacks; if such text contains the configured API key value, it SHALL be redacted before writing.

#### Scenario: Key never appears in logs
- **WHEN** any run completes, successfully or with failure
- **THEN** no log record anywhere in the file or console output contains the configured API key value
