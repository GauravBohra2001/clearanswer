# claim-extraction Specification

## Purpose
Extract checkable factual claims from a natural-language research report so that every downstream audit finding maps to a verbatim sentence the data can confirm or refute. The extractor is an LLM step bounded by deterministic filtering: the model proposes sentences, and the pipeline keeps only those it can prove were quoted from the report.

## Requirements

### Requirement: Verbatim sentence extraction
The system SHALL extract checkable factual claims as FULL sentences copied verbatim from the report (exact wording, punctuation, and casing), producing exactly one audit finding per extracted sentence. A checkable claim is a specific statement the data can confirm or refute: counts, percentages, comparisons, coverage statements, or rankings.

#### Scenario: Sentence with a measurable claim
- **WHEN** the report contains "Luminal A is the largest RNA subtype, accounting for about 62% of primary tumors with an RNA subtype call."
- **THEN** the extractor emits that exact sentence as one entry

#### Scenario: Compound sentence stays whole
- **WHEN** a single sentence contains two numbers (a total and a sub-count)
- **THEN** the extractor emits ONE entry containing the full sentence, never split into multiple entries

### Requirement: Non-claim sentences are skipped
The system SHALL skip sentences that carry no checkable factual claim: pure opinions or recommendations where the whole sentence is a suggestion, methodology framing or background with no measurable claim, italicized editor notes and framing lines, and opener sentences with no numbers.

#### Scenario: Recommendation dropped
- **WHEN** the report contains "We recommend future work combine all available layers."
- **THEN** the extractor does not emit that sentence

### Requirement: Main-clause rule for mixed sentences
The system SHALL keep a sentence when its MAIN clause is a factual claim, even if a trailing clause interprets or speculates; the verifier rules on the main clause.

#### Scenario: Factual claim with speculative tail
- **WHEN** a sentence states "Patients whose tumors had the highest ER-alpha protein responded best to hormone therapy, which suggests protein data could guide treatment research."
- **THEN** the extractor includes the full sentence because the main clause is a checkable factual claim

### Requirement: Verbatim verification filter
The system SHALL keep only extracted sentences that appear in the report after whitespace normalization (runs of whitespace collapsed, case-insensitive substring match). Paraphrases or model-invented wording are dropped so later evidence pointers stay reliable.

#### Scenario: Paraphrase rejected
- **WHEN** the model returns a sentence whose normalized form is not a substring of the normalized report text
- **THEN** that sentence is excluded from the extracted claims

### Requirement: Robust response parsing
The system SHALL parse the extractor's response defensively by extracting the first JSON object carrying a `claims` key (tolerating surrounding prose or code fences) and, failing that, the first bare JSON array of non-empty strings. An unparseable response yields an empty claim list rather than an error.

#### Scenario: JSON wrapped in code fences
- **WHEN** the model response wraps `{"claims": ["..."]}` in a markdown code fence
- **THEN** the parser still recovers the claims array

### Requirement: Extraction trace step
The system SHALL record one trace step for extraction capturing the report length, the number of candidate sentences returned by the model, and the number that matched the report verbatim.

#### Scenario: Trace entry written
- **WHEN** extraction completes with 5 candidate sentences of which 4 match the report
- **THEN** the trace contains an `extractor/extract` step whose reasoning records both counts
