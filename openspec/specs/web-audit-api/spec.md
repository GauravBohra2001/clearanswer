# web-audit-api Specification

## Purpose
Provide a browser-based demo of the Research Claim Auditor: post a report, watch extraction and verification progress live, review each finding with accept/override decisions, and export a judge-ready audit.json. The Flask wrapper is deliberately thin — the CLI entry point stays authoritative for judged runs — so it only adds job tracking on background threads, a submission-shaping step, and a validator round-trip around the unchanged pipeline.

## Requirements

### Requirement: Job lifecycle with background execution
The system SHALL accept an audit request, persist the posted report text to a per-job scratch file (one subdirectory per job under the temp dir so concurrent requests cannot clobber each other's input), register the job in a process-local store guarded by a lock, and start a daemon worker thread that runs the orchestrator end-to-end. Job state SHALL progress queued → extracting → verifying → done or error; workers SHALL record exceptions (type, message, short traceback) on the job rather than crashing the server.

#### Scenario: Request returns immediately
- **WHEN** POST /api/audit receives a non-empty report
- **THEN** it returns {job_id} at once and the pipeline runs on a background thread

#### Scenario: Pipeline failure recorded
- **WHEN** the orchestrator raises mid-run
- **THEN** the job state becomes error with the exception summary stored, and later status/result calls surface it

### Requirement: Flexible report input
The system SHALL accept the report text from a JSON body (report_text or report key), a multipart file upload (field names file, report, or report_file), or a plain form field. Missing or whitespace-only input SHALL be rejected with HTTP 400 and an explanatory error. The data directory and team name SHALL be taken from request values when provided, defaulting to the local oncosys-hackathon-challenge TCGA-BRCA raw directory and "clearanswer".

#### Scenario: File upload
- **WHEN** the client POSTs a multipart form with field "file" containing report.md
- **THEN** the audit starts from that file's decoded text

#### Scenario: Empty report rejected
- **WHEN** the posted report is empty or whitespace-only
- **THEN** the endpoint returns 400 with an error message and no job is created

### Requirement: Status and result polling
The system SHALL expose GET /api/status/<job_id> returning job_id, state, and a compact claims projection (id, claim_text, verdict, correct_value, summary, needs_human_review, limitation) that is empty until the audit is done, plus an error field when the job failed; unknown job ids SHALL return 404. GET /api/result/<job_id> SHALL return 202 while processing, 500 with the stored error when failed, and the full audit dict (including the private _trace) when done.

#### Scenario: Polling mid-run
- **WHEN** the UI polls status for a verifying job
- **THEN** it receives state "verifying" and an empty claims list without shipping the full result

### Requirement: Submission shaping policy
At export, the system SHALL produce a submission copy of the audit that drops the private _trace key, applies reviewer decisions per finding (decision accept or override; on override with a verdict, claim_verdict becomes the reviewer's while the tool's original is preserved under tool_verdict, reviewer_reason is recorded, and needs_human_review is cleared), sets severity from the FINAL verdict — supported → none, contradicted → high, insufficient_evidence → medium — forces confidence to "high" on every finding (verdicts come from deterministic computations, not sampling), and guarantees at least one evidence entry per finding with a claim-text pointer as fallback.

#### Scenario: Override preserves provenance
- **WHEN** the reviewer overrides F-002 from contradicted to supported with a reason
- **THEN** the exported finding has claim_verdict "supported", tool_verdict "contradicted", reviewer_decision "override", the reason, and needs_human_review false

#### Scenario: Severity follows final verdict
- **WHEN** an overridden finding ends as supported
- **THEN** its exported severity is "none" even if the tool originally set it higher

### Requirement: Export, validation, and download
The system SHALL write the submission copy to outputs/audit-<job_id>.json (UTF-8, indented), validate it by shelling out to the challenge repo's format/validate.py (30-second timeout) with a fallback to the built-in jsonschema validator when the challenge repo is absent, and return the relative path, download URL, valid flag, validator output, and finding count. Job ids that were never exported SHALL get 404 on GET /api/export/download/<job_id>; an existing export SHALL be served as an attachment named audit.json.

#### Scenario: Validator round-trip
- **WHEN** the exported file passes the challenge validator
- **THEN** the response carries valid true and the validator's output text for the UI to display

### Requirement: Permissive CORS for local demo
The system SHALL add Access-Control-Allow-Origin "*", allowed methods GET/POST/OPTIONS, and allowed headers Content-Type/Authorization to every API response, and answer OPTIONS preflights with 204, so judges may host the UI elsewhere.

#### Scenario: Preflight
- **WHEN** a browser sends OPTIONS to /api/export/<job_id>
- **THEN** the server responds 204 with the CORS headers

### Requirement: Three-state reviewer UI
The frontend SHALL present three states: ready (drop zone for .txt/.md files plus a textarea, audit button enabled only when input is present, dataset info strip), working (an Extract → Verify → Report timeline that advances by job state, per-claim rows whose verdict badges animate as results arrive, and a status line such as "Verified N of M claims…"), and done (summary counts of supported/contradicted/insufficient findings, one row per claim with id pill, claim text, limitation one-liner, verdict badge, and a "Needs review" badge when flagged). The UI SHALL poll /api/status every 1500 ms during the working state and fetch the full result on completion.

#### Scenario: Live progress
- **WHEN** the audit is verifying its third of five claims
- **THEN** the timeline shows Verify active and the status line reflects verified progress so far

### Requirement: Accept/override review workflow
Each done-state claim row SHALL offer Accept and Override actions stored purely in browser state (the server stays stateless until export). Override SHALL open an inline form with the three verdict pills — pre-selecting the current verdict so a reviewer can just add a reason — a reason input, and confirm/cancel. A progress line SHALL show "N of M claims reviewed" with a matching bar.

#### Scenario: Default verdict preserved
- **WHEN** the reviewer opens Override on a supported claim
- **THEN** the "supported" pill is pre-selected and confirming without changes records an accept-equivalent override with the current verdict

### Requirement: Evidence drill-down per claim
Clicking a claim row SHALL open a single-open accordion showing, from data already present in the result (never generated or paraphrased): for contradicted findings, a "Report claimed → Data shows" comparison block; a Sources tree rendering each evidence pointer (file or id, kind, note, release); a Caveat / "What was missing" section when a limitation exists; and the agent reasoning steps belonging to that claim — recovered by segmenting the verifier trace on plan-step boundaries and matching the exact claim text — behind a show/hide toggle.

#### Scenario: Reasoning filtered to one claim
- **WHEN** the user opens the drill-down for F-003
- **THEN** only the verifier steps between F-003's plan step and the next plan step are shown

### Requirement: Export button and reset
The export button SHALL pack all browser review decisions as overrides (finding_id, decision, optional verdict and reason), POST them to /api/export/<job_id>, display PASS or FAIL with the validator's first output line and the written path, and trigger a browser download of audit.json. "New Audit" SHALL clear the poll timer, job id, stored result, review state, and all input fields, and return the UI to the ready state.

#### Scenario: Export surfaces validator verdict
- **WHEN** the export completes with valid true
- **THEN** the status line reads "PASS · …" plus the written path and the browser downloads audit.json
