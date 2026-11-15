# guardrails Specification

## Purpose
Enforce the hackathon's out-of-scope rule — no diagnosis, no treatment recommendation, no risk score, no re-identification, no regulatory or clinical production claim — with fast, explicit, explainable regex checks that never call an LLM. Guards run both before verification (on the raw report text) and after verification (on each ClaimResult), and every flag names its category and the matched snippet so a reviewer can see exactly why something was caught.

## Requirements

### Requirement: Clinical and prognostic guards
The system SHALL flag clinical recommendation language (recommend/prescribe/administer phrasing, first-line or second-line treatment options, "standard of care"), diagnosis language ("diagnosed with", "diagnosis of", "this patient has"), and risk or prognosis language (will die/survive/relapse/recur/respond, individual risk score/estimate/prediction, prognosis quality statements).

#### Scenario: Standard of care flagged
- **WHEN** pre_check is run on text containing "standard of care"
- **THEN** it returns a clinical_recommendation issue quoting the matched snippet

### Requirement: Privacy and re-identification guards
The system SHALL flag re-identification attempts (re-identify/deanonymize, matching to named patients, patient name/address/contact lookups), personal data patterns (US phone numbers, SSN shapes, email addresses), and full TCGA sample barcodes — a complete TCGA-XX-XXXX[-NN] barcode names an individual participant even though the data is de-identified.

#### Scenario: Barcode flagged
- **WHEN** pre_check is run on text containing "TCGA-3C-AAAU-01"
- **THEN** it returns an individual_barcode issue because a full barcode names one participant

### Requirement: Regulatory, injection, and input guards
The system SHALL flag regulatory or production claims (FDA-approved, CE-marked, clinically validated, production-ready, HIPAA-compliant), prompt-injection attempts ("ignore previous instructions", role markers such as "system:", </system> tags, jailbreak terms), and impossible numeric shares (negative percentages or percentages strictly above 100).

#### Scenario: Impossible percentage flagged
- **WHEN** pre_check is run on text containing "150% of tumors" or "-5% of tumors"
- **THEN** it returns an invalid_input issue for the out-of-range share

### Requirement: Pre-check surfaces issues without refusing
pre_check SHALL return a list of issue strings formatted as "<category>: '<matched snippet>'", with at most one hit per category, and an empty list (or [] for non-string/empty input) when nothing matches. The orchestrator SHALL record the pre-check result in the trace but continue processing, because the report is researcher-written: the guard surfaces suspicious content for review rather than refusing the audit.

#### Scenario: Clean text passes
- **WHEN** pre_check is run on a factual cohort sentence with no flagged patterns
- **THEN** it returns an empty list and verification proceeds normally

#### Scenario: Recommendation surfaced, processing continues
- **WHEN** pre_check finds "we recommend prescribing" in the report
- **THEN** the trace records a clinical_recommendation issue and the pipeline still verifies the remaining claims

### Requirement: Post-check flags weak verdicts for review
post_check SHALL mutate and return a ClaimResult, setting needs_human_review to True when the confidence is low or when a supported/contradicted verdict carries fewer than two evidence entries (a single tool call is worth a human glance). It SHALL NOT overwrite an existing limitation with a guard prefix.

#### Scenario: Low-confidence flagged
- **WHEN** post_check receives a budget-exhausted result at confidence low
- **THEN** needs_human_review is set True on the returned result

#### Scenario: Single-evidence decisive verdict flagged
- **WHEN** post_check receives a supported ClaimResult with exactly one evidence entry
- **THEN** needs_human_review is set True
