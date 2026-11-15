# cli-runner Specification

## Purpose
Provide the single judged entry point for the Research Claim Auditor: a command-line script that takes a TCGA-BRCA release directory and a research report, runs the full extract/verify pipeline, writes a schema-validated audit.json, prints a human-readable summary of every finding, and exits non-zero when validation fails. The judge points this at an envelope-unsealed release and the report from the envelope — it is the only script the judge needs to run.

## Requirements

### Requirement: Command-line contract
The system SHALL accept exactly two positional arguments — the TCGA-BRCA release directory (a raw layout or an envelopes/opened/<n>/release/ path) and the research report Markdown file — plus optional flags: --output for the audit JSON path (default audit.json), --verbose to print the full agent trace in Markdown, and --team for the producer team name recorded in the audit (default "clearanswer").

#### Scenario: Envelope release
- **WHEN** the judge runs `python run.py envelopes/opened/E07/release/data/tcga-brca/raw report.md`
- **THEN** the pipeline audits the report against that envelope's release and writes audit.json

### Requirement: Console summary of findings
After the pipeline completes, the script SHALL print "Extracted N claims from <report>." followed by one line per finding in the form `[F-001] VERDICT (data shows <correct_value>): <claim_text>` — with the parenthetical only for contradicted findings that carry a correct_value — then a validation status line and "Audit written to: <path>".

#### Scenario: Contradicted line
- **WHEN** F-002 is contradicted with correct_value "49.9% (421 of 844)"
- **THEN** its summary line reads `[F-002] CONTRADICTED (data shows 49.9% (421 of 844)): <claim text>`

### Requirement: Self-validation before exit
The script SHALL validate the written audit document against findings.schema.json v0.2 (plus the id-graph checks) and print either "validation: OK (matches findings.schema.json v0.2)" or a "validation FAILED:" block listing every error. The process SHALL exit 0 only when validation passes and exit 1 when it fails, so a judge's shell can gate on the return code.

#### Scenario: Invalid output fails loudly
- **WHEN** validation returns errors
- **THEN** each error is printed on its own line and the script exits with status 1

### Requirement: Pipeline failure surfacing
If the pipeline raises (missing data directory, missing API key, LLM failure after retries), the script SHALL print "ERROR: <ExceptionType>: <message>" to stderr and exit 1 without writing a partial audit file.

#### Scenario: Missing release directory
- **WHEN** data_dir does not exist
- **THEN** the script prints an ERROR line naming FileNotFoundError and exits 1

### Requirement: Optional trace dump
With --verbose, the script SHALL print the complete agent trace in Markdown (every step's when/duration/reasoning/input/output/tool calls) under a "----- TRACE -----" banner after the summary; without the flag the trace stays inside audit.json only.

#### Scenario: Verbose run
- **WHEN** --verbose is passed
- **THEN** the Markdown trace from the orchestrator's collector is printed in full
