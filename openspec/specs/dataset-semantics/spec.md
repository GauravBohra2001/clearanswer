# dataset-semantics Specification

## Purpose
Encode the TCGA-BRCA dataset's structure, column meanings, known limitations, and topics the data fundamentally cannot answer into a single declarative schema. The semantic layer is what makes the verifier honest: it tells the agent which tables exist, which columns are YES/NO flags rather than response measures, and which claim topics must short-circuit to insufficient_evidence before any query runs. The file is designed to be swapped per dataset (TCGA-LUAD, TCGA-PRAD, etc.) without touching agent code.

## Requirements

### Requirement: Declarative dataset schema
The system SHALL maintain a declarative schema describing the dataset name and cohort description (1,247 samples in the manifest; 1,101 primary tumors, 139 normal tissue, 7 metastatic; six data layers; 535 primaries with all five non-clinical layers), every table (file, description, key column, columns with dtype/description/values/use_for/limitation), a map of supported operations to their backing functions, and a list of topics the dataset cannot answer.

#### Scenario: Schema serves prompts
- **WHEN** get_schema is called
- **THEN** it returns the full TCGA-BRCA schema dictionary including tables, operations, and cannot_answer entries

### Requirement: Therapy flags documented as flags only
The system SHALL document the three therapy columns in clinical (radiation_therapy, targeted_molecular_therapy, additional_pharmaceutical_therapy) as YES/NO-only indicators carrying an explicit limitation that they record whether therapy was given, NOT treatment response or outcome. The schema SHALL list, per table, a does_not_have set naming fields that do not exist (hormone therapy, endocrine therapy, treatment response, drug efficacy, tamoxifen, aromatase inhibitor, responders, and related terms).

#### Scenario: Limitation surfaced in prompt
- **WHEN** the schema summary is rendered for the verifier's system prompt
- **THEN** each therapy column line carries its LIMITATION text and the clinical table lists its DOES NOT HAVE entries

### Requirement: Cannot-answer pre-check
The system SHALL provide check_cannot_answer(claim) that returns the matching cannot_answer entry when every word of a topic phrase appears in the claim (treatment response, drug efficacy, hormone therapy, endocrine therapy, "responded best", protein-treatment correlation, causal), or when any does_not_have term (underscore form or space-separated form) appears in the claim; it SHALL return None for claims that can be checked against the data. Each entry SHALL carry a reason naming what would be needed instead (e.g., METABRIC or a neo-adjuvant endocrine therapy trial for hormone-therapy claims).

#### Scenario: Topic phrase match
- **WHEN** check_cannot_answer is called with a claim containing "hormone therapy"
- **THEN** it returns the hormone-therapy entry whose reason names radiation_therapy, targeted_molecular_therapy, and additional_pharmaceutical_therapy as YES/NO flags only

#### Scenario: Missing-field match
- **WHEN** a claim mentions "tamoxifen"
- **THEN** the pre-check matches the does_not_have term and returns a synthesized entry naming the table and file that lack it

### Requirement: Table relevance lookup
The system SHALL provide find_table_for_claim(claim) returning the names of tables whose use_for keywords (table-level or column-level) have any word appearing in the claim, so the verifier can be pointed at relevant tables without enumerating all columns.

#### Scenario: Subtype claim
- **WHEN** find_table_for_claim is called with a sentence about RNA subtype percentages
- **THEN** clinical is returned as relevant because its PAM50Call_RNAseq column's use_for entries include "rna subtype" and "subtype percentages"

### Requirement: Compact prompt summary
The system SHALL render the schema as a compact plain-text summary for inclusion in LLM prompts: dataset name and description, each table with its file and columns (description, values, LIMITATION lines), DOES NOT HAVE lists, available operations, and the full CANNOT ANSWER list with reasons.

#### Scenario: Summary content
- **WHEN** get_schema_summary_for_prompt is called
- **THEN** the output contains the dataset description, a CANNOT ANSWER section listing all seven topics with their reasons, and per-column LIMITATION lines for the therapy flags
