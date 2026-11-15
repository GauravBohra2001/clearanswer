# evidence-contract Specification

## Purpose
Define the compile-time contract between a claim verdict and its proof. A ClaimResult cannot be constructed without the evidence the shared audit format requires: contradicted demands a correct_value, supported and contradicted demand at least one Evidence pointer. The only verdict that may carry no evidence is insufficient_evidence — because the point of that verdict is that the data cannot answer the claim.

## Requirements

### Requirement: Closed vocabularies
The system SHALL define closed vocabularies for verdicts (supported, contradicted, insufficient_evidence), confidences (high, medium, low), severities (high, medium, low, none), and evidence kinds (sample, patient, gene, protein, slide, file, release, analysis, claim, row). Any ClaimResult or Evidence constructed with a value outside these vocabularies SHALL be rejected at construction time.

#### Scenario: Invalid verdict rejected
- **WHEN** a ClaimResult is constructed with claim_verdict "maybe"
- **THEN** construction raises ValueError naming the allowed verdicts

### Requirement: Evidence pointer validation
An Evidence pointer SHALL carry a kind from the evidence-kind vocabulary and a non-empty id, plus optional release, file, and note fields. Serialization to dict SHALL omit any of the optional fields that are unset so the audit output stays compact and schema-valid.

#### Scenario: Unknown kind rejected
- **WHEN** an Evidence is constructed with kind "citation"
- **THEN** construction raises ValueError naming the allowed evidence kinds

#### Scenario: Optional fields omitted
- **WHEN** an Evidence(kind="file", id="clinical.tsv") with no release, file, or note is serialized
- **THEN** its dict contains only kind and id

### Requirement: Contradicted requires a correct value
A ClaimResult with verdict contradicted SHALL require a non-empty correct_value at construction time; the contract SHALL be enforced in __post_init__ so an invalid object can never exist, not merely fail later validation.

#### Scenario: Missing correct_value rejected
- **WHEN** a contradicted ClaimResult is constructed without correct_value
- **THEN** construction raises ValueError stating that a contradicted claim requires a non-empty correct_value

### Requirement: Decisive verdicts require evidence
A ClaimResult with verdict supported or contradicted SHALL require at least one Evidence entry at construction time. An insufficient_evidence ClaimResult SHALL be constructible with no evidence, since the absence of data is itself the finding.

#### Scenario: Supported without evidence rejected
- **WHEN** a supported ClaimResult is constructed with an empty evidence list
- **THEN** construction raises ValueError requiring at least one evidence entry

#### Scenario: Insufficient without evidence allowed
- **WHEN** an insufficient_evidence ClaimResult is constructed with no evidence
- **THEN** construction succeeds and the result serializes with an empty evidence list

### Requirement: Canonical constructors
The system SHALL provide module-level constructors rather than raw dataclass construction: supported(claim_text, evidence, ...) defaulting to confidence high and severity none; contradicted(claim_text, correct_value, evidence, ...) defaulting to confidence high and severity high; insufficient(claim_text, reason, ...) defaulting to confidence medium, severity none, needs_human_review True, with the reason stored in both limitation and reasoning.

#### Scenario: Insufficient constructor defaults
- **WHEN** insufficient is called with a claim and a reason naming the missing data
- **THEN** it returns a ClaimResult with verdict insufficient_evidence, needs_human_review True, and the reason present in both limitation and reasoning

### Requirement: Conditional serialization fields
ClaimResult.to_dict SHALL always include claim_text, claim_verdict, confidence, severity, evidence (as dicts), needs_human_review, and reasoning, and SHALL include correct_value and limitation only when they are set.

#### Scenario: Supported serializes without correct_value
- **WHEN** a supported ClaimResult with no correct_value or limitation is serialized
- **THEN** its dict omits both keys while retaining the seven always-present fields
