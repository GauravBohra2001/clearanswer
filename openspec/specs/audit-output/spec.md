# audit-output Specification

## Purpose
Translate internal ClaimResult objects into the shared findings.schema.json v0.2 format that the organizer's checker reads, and validate the result against that schema plus the hackathon's reference id-graph rules. This module is the only place in the system where the shared-format wording lives: everything else works with ClaimResult, and conversion happens here at the edge. Findings are enriched with reviewer-facing context (next_step, why_it_matters) and a denser evidence chain a human auditor expects to see.

## Requirements

### Requirement: Audit document assembly
The system SHALL assemble an audit document containing format_version "0.2", a producer block (team, product "research-claim-auditor", track "evidence-navigator"), a data block naming dataset TCGA-BRCA with one release entry carrying the release name and per-file SHA-256 checksums (hash_of "file"), a question string summarizing the check with the report path when available, and findings built in order from the claim results. The full agent trace SHALL be attached under a private "_trace" key that is excluded from schema validation but preserved for reviewers.

#### Scenario: Release naming
- **WHEN** the release directory sits under envelopes/opened/3/release/...
- **THEN** the data block names the release "3"; a raw layout names it "raw"; any other directory uses its own name

### Requirement: Finding shape and stable ids
Each finding SHALL carry a stable id of the form F-{index:03d} (F-001 for the first claim), kind "claim_check", a verdict-prefixed summary ("Supported: ", "Contradicted: ... Correct value: X", or "Insufficient evidence: ") with the claim text whitespace-collapsed and truncated to 120 characters, severity and confidence from the result, the verbatim claim_text, the claim_verdict, needs_human_review, and — only when set — correct_value and limitation.

#### Scenario: First finding id
- **WHEN** the first claim result is converted
- **THEN** its finding id is "F-001"

### Requirement: Reviewer-facing evidence chain
Each finding's evidence SHALL be a reviewer-facing chain, not the raw tool pointers: first a claim pointer (kind "claim", id = finding id, note = claim text) so the sentence under review always comes first; then every deduplicated file and analysis pointer from the verifier, with file pointers stamped with the release name when missing; then a synthesized cohort_trace analysis line when any analysis note contains counts or a distribution (=, /, or %). When an insufficient-evidence finding would otherwise carry only the claim pointer, a data_scope_check analysis pointer SHALL be added carrying the limitation so reviewers see what was searched.

#### Scenario: Deduplication
- **WHEN** the verifier emitted two file pointers for clinical.tsv
- **THEN** the finding's evidence contains exactly one, plus the leading claim pointer

#### Scenario: Scope check fallback
- **WHEN** an insufficient_evidence finding has no tool evidence but a limitation
- **THEN** its evidence ends with a data_scope_check analysis pointer whose note is the limitation

### Requirement: Treatment-response limitation rewrite
For insufficient_evidence findings whose claim text matches treatment-response vocabulary (hormone therapy, endocrine therapy, tamoxifen, aromatase, neoadjuvant/adjuvant, responded to/best, responders, treatment/therapy/pathological response), the system SHALL replace the limitation with a canonical string that names the columns that DO exist (radiation_therapy, targeted_molecular_therapy, additional_pharmaceutical_therapy as yes/no flags, plus new_tumor_event_after_initial_treatment and days_to_new_tumor_event) and states what dataset would be needed (METABRIC or a neo-adjuvant endocrine therapy trial).

#### Scenario: Hormone-therapy claim
- **WHEN** an insufficient_evidence finding's claim mentions "hormone therapy"
- **THEN** its limitation is the canonical treatment-response string, not the model's free-text reason

### Requirement: Verdict-specific reviewer context
Every finding SHALL carry why_it_matters and next_step text chosen by verdict: supported explains the number matches and can be cited; contradicted warns that downstream figures inherit the error and next_step quotes the correct_value to apply; insufficient_evidence explains the release does not record what the sentence requires and next_step suggests removing/rewording or rerunning against a dataset that records it.

#### Scenario: Contradicted next step
- **WHEN** a finding is contradicted with correct_value "49.9% (421 of 844)"
- **THEN** its next_step instructs correcting the number to that exact value before sharing

### Requirement: Schema and id-graph validation
The system SHALL validate an audit document with jsonschema Draft 2020-12 against the challenge repo's format/findings.schema.json (private "_"-prefixed keys stripped first) and additionally enforce the hackathon's reference id-graph rules: every repairs[].addresses entry must name an existing finding id, and every decisions[].repair_id must name an existing repair id. Validation SHALL return a list of human-readable error strings (empty when valid).

#### Scenario: Unknown repair target
- **WHEN** a decision references a repair_id that does not exist in the document
- **THEN** validation reports an error naming the unknown repair

### Requirement: Deterministic file writing
The system SHALL write the audit document as UTF-8 JSON with 2-space indentation to the requested path and return the written Path.

#### Scenario: Write and reuse
- **WHEN** write_audit_json is called with a dict and a path
- **THEN** the file contains the indented JSON and the returned Path points at it
