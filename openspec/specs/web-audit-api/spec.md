# web-audit-api Specification

## Purpose
Provide a browser-based demo of the Research Claim Auditor: post a report (text or PDF), watch extraction and verification progress with live claim counts, review each finding with accept/override decisions, and export either a judge-ready audit.json or a self-contained HTML report. The Flask wrapper is deliberately thin — the CLI entry point stays authoritative for judged runs — so it only adds job tracking on background threads, a submission-shaping step, and validator round-trips around the unchanged pipeline.

## Requirements

### Requirement: Job lifecycle with background execution
The system SHALL persist posted report text to a per-job scratch file (one subdirectory per job under the temp dir so concurrent requests cannot clobber each other), register the job in a process-local store guarded by a lock, and run the orchestrator on a daemon worker thread. State SHALL progress queued → extracting → verifying → done or error; worker exceptions (type, message, short traceback) SHALL be recorded on the job rather than crash the server.

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

### Requirement: PDF upload extraction
Uploaded .pdf files SHALL be converted to text server-side with pdfplumber. Each page SHALL be split at the horizontal midpoint: when both halves carry substantial text (two-column layout) they are concatenated in reading order, otherwise the full page is extracted; extraction SHALL preserve tight word spacing (x_tolerance 2). PDFs yielding no selectable text — scanned or image-only pages — SHALL be rejected with HTTP 400 and an OCR hint, as SHALL a missing pdfplumber installation.

#### Scenario: Two-column paper
- **WHEN** a dropped .pdf has two-column academic pages
- **THEN** each page's left half is extracted before its right half so sentences are not interleaved

#### Scenario: Scanned PDF rejected
- **WHEN** the uploaded PDF contains only images and no selectable text
- **THEN** the endpoint returns 400 explaining that OCR must run first

### Requirement: Status and result polling
The system SHALL expose GET /api/status/<job_id> returning job_id, state, extracted_count and verified_count during the run, a compact claims projection (id, claim_text, verdict, correct_value, summary, needs_human_review, limitation) empty until done, plus an error field when the job failed; unknown job ids SHALL return 404. GET /api/result/<job_id> SHALL return 202 while processing, 500 with the stored error when failed, and the full audit dict including the private _trace when done.

#### Scenario: Polling mid-run
- **WHEN** the UI polls status while the third of five claims is being verified
- **THEN** it receives state "verifying", extracted_count 5, verified_count 2, and an empty claims list without shipping the full result

### Requirement: Submission shaping policy
At export, the system SHALL produce a submission copy that drops the private _trace key, applies reviewer decisions (on override, claim_verdict becomes the reviewer's while tool_verdict preserves the original; reviewer_reason recorded; needs_human_review cleared), sets severity from the FINAL verdict — supported none, contradicted high, insufficient_evidence medium — forces confidence "high" on every finding, and guarantees at least one evidence entry per finding.

#### Scenario: Override preserves provenance
- **WHEN** the reviewer overrides F-002 from contradicted to supported with a reason
- **THEN** the exported finding has claim_verdict "supported", tool_verdict "contradicted", reviewer_decision "override", the reason, and needs_human_review false

#### Scenario: Severity follows final verdict
- **WHEN** an overridden finding ends as supported
- **THEN** its exported severity is "none" even if the tool originally set it higher

### Requirement: Export, validation, and download
The system SHALL write the submission copy to outputs/audit-<job_id>.json (UTF-8, indented), validate it via the challenge repo's format/validate.py with a 30-second timeout — falling back to the built-in jsonschema validator when the repo is absent — and return the relative path, download URL, valid flag, validator output, and finding count. Downloading an unexported job SHALL return 404; an existing export SHALL be served as an attachment named audit.json.

#### Scenario: Validator round-trip
- **WHEN** the exported file passes the challenge validator
- **THEN** the response carries valid true and the validator's output text for the UI to display

### Requirement: Standalone HTML report export
The system SHALL expose /api/report/<job_id>/download.html (GET and POST) rendering a completed audit as a self-contained HTML page. It SHALL apply the same submission-shaping policy as JSON export, including reviewer overrides in the request body when present, so the report reflects exactly what judges will see. Unknown jobs SHALL return 404, failed jobs 500, unfinished jobs 202; on success the response is the rendered page as an attachment named clearanswer-audit.html.

#### Scenario: Report carries overrides
- **WHEN** the reviewer POSTs overrides to download.html for a finished job
- **THEN** the returned HTML shows each overridden finding's reviewer decision with the tool verdict preserved

#### Scenario: HTML report button
- **WHEN** the reviewer clicks the HTML report button in the done state
- **THEN** the browser downloads clearanswer-audit.html rendered with the same overrides a JSON export would use

### Requirement: Permissive CORS for local demo
The system SHALL add Access-Control-Allow-Origin "*", allowed methods GET/POST/OPTIONS, and allowed headers Content-Type/Authorization to every API response, and answer OPTIONS preflights with 204 on every endpoint — including the HTML report endpoint — so judges may host the UI elsewhere.

#### Scenario: Preflight
- **WHEN** a browser sends OPTIONS to /api/export/<job_id>
- **THEN** the server responds 204 with the CORS headers

### Requirement: Three-state reviewer UI
The frontend SHALL present three states: ready (a drop zone accepting .txt, .md, or .pdf files plus a textarea, audit button enabled only when input is present), working (an Extract → Verify → Report timeline advancing by job state plus a live-counts progress line, e.g. "Verifying 3 of 16 claims…"), and done (summary counts per verdict plus one row per claim with id pill, claim text, verdict badge, and Needs-review badge when flagged). The UI SHALL poll /api/status every 1500 ms while working.

#### Scenario: PDF stays a file until submit
- **WHEN** the reviewer drops a .pdf into the drop zone
- **THEN** the audit button enables and submission uploads the raw file as multipart so the server extracts its text

#### Scenario: Live progress
- **WHEN** the audit has extracted 16 claims and verified 3 of them
- **THEN** the timeline shows Verify active and the status line reads "Verifying 3 of 16 claims…"

### Requirement: Accept/override review workflow
Each done-state claim row SHALL offer Accept and Override actions stored purely in browser state (the server stays stateless until export). Override SHALL open an inline form with the three verdict pills — pre-selecting the current verdict so a reviewer can just add a reason — a reason input, and confirm/cancel. A progress line SHALL show "N of M claims reviewed" with a matching bar.

#### Scenario: Default verdict preserved
- **WHEN** the reviewer opens Override on a supported claim
- **THEN** the "supported" pill is pre-selected and confirming without changes records an accept-equivalent override with the current verdict

### Requirement: Evidence drill-down per claim
A claim row click SHALL open a single-open accordion showing only data already in the result (never generated or paraphrased): a "Data checked" box (source files, release, up to three calculations), an Impact section when the finding carries why_it_matters, next_step, or cannot_tell, a Caveat / What-was-missing block when a limitation exists, alternatives for other columns answering the same question, a Sources tree of every evidence pointer, and that claim's verifier reasoning steps.

#### Scenario: Reasoning filtered to one claim
- **WHEN** the user opens the drill-down for F-003
- **THEN** only the verifier steps between F-003's plan step and the next plan step are shown

#### Scenario: Sources and reasoning collapsed
- **WHEN** the user opens a claim's drill-down panel
- **THEN** the sources tree and reasoning steps are hidden behind "Show" toggles until clicked

### Requirement: Export button and reset
The export button SHALL pack all browser review decisions as overrides (finding_id, decision, optional verdict and reason), POST them to /api/export/<job_id>, display PASS or FAIL with the validator's first output line and the written path, and trigger a browser download of audit.json. "New Audit" SHALL clear the poll timer, job id, stored result, review state, dropped-file and PDF state, and all input fields, returning the UI to ready.

#### Scenario: Export surfaces validator verdict
- **WHEN** the export completes with valid true
- **THEN** the status line reads "PASS · …" plus the written path and the browser downloads audit.json
