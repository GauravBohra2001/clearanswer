# claim-verification Specification

## Purpose
Verify one extracted claim at a time against the frozen TCGA-BRCA release using a plan/query/execute/interpret/reflect loop. The LLM decides HOW to check a claim; deterministic pandas tools decide WHAT the number is, so every verdict is backed by a computation a reviewer or judge can rerun.

## Requirements

### Requirement: Semantic pre-check short-circuit
The system SHALL run a semantic-layer pre-check before any tool call. When a claim's topic matches a `cannot_answer` entry (treatment response, drug efficacy, hormone therapy, endocrine therapy, "responded best", protein-treatment correlation, causal claims), the verifier SHALL return an `insufficient_evidence` verdict immediately without tool calls, at high confidence, with evidence that names the blocked topic and the files inspected.

#### Scenario: Hormone therapy claim
- **WHEN** a claim mentions hormone therapy response
- **THEN** the verifier returns insufficient_evidence with the schema's reason (no hormone-therapy column; would require METABRIC or a neo-adjuvant endocrine therapy trial) and no data_query call is made

### Requirement: Tool-use verification loop
The system SHALL verify each claim through an Anthropic tool-use loop bounded by a hard step budget of 10 LLM turns. Each turn the model may call `data_query`, `schema_info`, or `manifest_lookup`; every tool result is returned to the model and recorded in the trace as a query/execute step carrying the tool name, arguments, and a trimmed result.

#### Scenario: Multi-tool verification
- **WHEN** verifying "Of the 1,101 primary tumors in the release, 535 have survival, mutation, copy number, RNA and protein data."
- **THEN** the verifier may call manifest_lookup and/or data_query, receives exact counts from the tools, and records each call in the trace

### Requirement: Finalize contract
The system SHALL require the model to record its verdict through a dedicated `finalize_verdict` tool called exactly once, carrying verdict (supported | contradicted | insufficient_evidence), confidence, severity, and reasoning, plus correct_value for contradicted verdicts. Optional fields let the model attach claim-specific context: limitation, evidence_files, why_it_matters, next_step, cannot_tell, and alternatives (column/value/note entries for other columns answering the same question).

#### Scenario: Verdict recorded
- **WHEN** the model calls finalize_verdict with verdict "contradicted" and correct_value "49.9% (421 of 844)"
- **THEN** the verifier builds the ClaimResult from that input and stops the loop

#### Scenario: Alternatives captured
- **WHEN** finalize_verdict notes that ER status by IHC gives a different number than PAM50 Luminal
- **THEN** the ClaimResult carries an alternatives entry with column, value, and note

### Requirement: Compound sentences use worst-part-wins
The system SHALL check EVERY number in a compound sentence and assign ONE verdict to the whole sentence: supported only when every sub-claim matches the data within reasonable rounding; contradicted when at least one sub-claim disagrees, with correct_value listing what the data shows for each wrong sub-claim separated by "; ".

#### Scenario: One wrong number in a two-number sentence
- **WHEN** a sentence states both "1,101 primary tumors" (correct) and "62% Luminal A" (wrong; the data shows 49.9%)
- **THEN** the verdict is contradicted and correct_value names the wrong sub-claim with the data's value

### Requirement: Step-budget fallback
The system SHALL return a defensive `insufficient_evidence` verdict at low confidence when the model exhausts the step budget without calling finalize_verdict. The fallback SHALL include evidence for every file the verifier actually queried plus an analysis pointer marked "budget_exhausted" explaining the stop.

#### Scenario: Budget exhausted
- **WHEN** 10 turns pass with no finalize_verdict call
- **THEN** the claim is verdicted insufficient_evidence at low confidence and its evidence lists the files queried before the stop

### Requirement: Evidence assembly from tool history
The system SHALL build a finding's evidence from the tool history: one deduplicated file pointer per successful tool call that cites a source file, one analysis pointer per successful data_query carrying the query description and a short result summary, plus any files the model explicitly declared. A supported verdict with no tool evidence SHALL carry an analysis marker "model_asserted_match".

#### Scenario: File pointers deduplicated
- **WHEN** two successful data_query calls both cite clinical.tsv
- **THEN** the finding contains exactly one file pointer for clinical.tsv and up to two analysis pointers describing the computations

### Requirement: Missing correct_value recovery
When a contradicted verdict arrives without a correct_value, the system SHALL recover one from the most recent successful data_query result; if none exists it SHALL use the literal "not stated by verifier" so the evidence contract (contradicted requires correct_value) is never violated.

#### Scenario: Model omits correct_value
- **WHEN** finalize_verdict says contradicted with an empty correct_value and a prior data_query returned a PAM50 distribution
- **THEN** the finding's correct_value is a short summary of that query result

### Requirement: Rounding-tolerance safety net
The system SHALL apply a tolerance safety net when the verdict is contradicted: compare the first number of the claim with the first number of correct_value — percentages within ±0.5pp, approximate-wording claims within max(1.5pp, 5% relative), all other values exact match. A value within tolerance SHALL upgrade the verdict to supported at severity none, append a tolerance note to reasoning, and set it as limitation when absent.

#### Scenario: Rounded percentage upgraded
- **WHEN** finalize_verdict says contradicted with correct_value "49.9% (421 of 844)" but the claim said "50%"
- **THEN** the verdict becomes supported at severity none and the reasoning carries a tolerance note

#### Scenario: Count mismatch stays contradicted
- **WHEN** the claim states 620 primary tumors but correct_value shows 535
- **THEN** the difference exceeds tolerance and the verdict remains contradicted

### Requirement: Insufficient evidence limitation quality
For insufficient_evidence verdicts, the system SHALL record in the limitation field the specific columns searched and the dataset or measure that would be needed to answer the claim.

#### Scenario: Treatment response limitation
- **WHEN** a claim about hormone therapy response cannot be checked
- **THEN** the limitation names radiation_therapy, targeted_molecular_therapy, and additional_pharmaceutical_therapy as yes/no flags and states that no response measure exists in the release
