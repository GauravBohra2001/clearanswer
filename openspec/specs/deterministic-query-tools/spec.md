# deterministic-query-tools Specification

## Purpose
Expose the TCGA-BRCA release to the verifier agent through three small, deterministic tools — data_query, schema_info, and manifest_lookup — so that every number in a verdict comes from a rerunnable pandas computation rather than model memory.

## Requirements

### Requirement: Deterministic data queries
The system SHALL provide a `data_query` tool supporting the operations count, filter, aggregate (mean/sum/min/max/median), value_counts, describe, compare (per-group n plus aggregate), and unique against any of the six data layers or the two manifests. Queries accept an optional `primary_only` flag that restricts to primary-tumor samples and `where` conditions supporting the operators ==, !=, >, >=, <, <=, in, and not_in.

#### Scenario: PAM50 distribution of primary tumors
- **WHEN** data_query is called with operation value_counts on layer clinical, column PAM50Call_RNAseq, primary_only true
- **THEN** the result contains per-subtype counts and percentages computed over non-null values

#### Scenario: Filtered count
- **WHEN** data_query is called with operation count on layer clinical, where breast_carcinoma_estrogen_receptor_status equals Positive, primary_only true
- **THEN** the result is the exact row count after applying the filter

### Requirement: Self-describing query results
Every successful tool result SHALL carry an ok flag, the source file name, and a human-readable query_description (operation, layer, column, group_by, primary_only, where) so the agent can cite it and a reviewer can retrace it. Failures (unknown layer, unknown operation, missing column, unknown operator) SHALL be returned as error results instead of raised exceptions so the model can recover and retry.

#### Scenario: Unknown column
- **WHEN** data_query references a column that does not exist in the layer
- **THEN** the tool returns an ok:false error naming the missing column and the verification loop continues

### Requirement: Schema introspection
The system SHALL provide a `schema_info` tool with actions list_layers, columns, dtypes, sample_values, unique_values, describe_column, and search_columns (substring match across column names in one or every layer). Long column lists SHALL be truncated with an explicit truncated flag.

#### Scenario: Search for therapy columns
- **WHEN** schema_info is called with action search_columns and query "therap"
- **THEN** the result lists matching column names grouped by layer, including radiation_therapy, targeted_molecular_therapy, and additional_pharmaceutical_therapy in clinical

### Requirement: Manifest lookups
The system SHALL provide a `manifest_lookup` tool with actions count_samples (by sample_type), count_with_layers (samples having ALL requested layer flags, with denominator), sample_info (full manifest record for one barcode), layer_availability (n and percent per layer flag), and has_all_layers (per-flag presence for one barcode). Unknown barcodes SHALL return a not-found result rather than an error.

#### Scenario: Cohort count
- **WHEN** manifest_lookup is called with action count_samples and sample_type "Primary Tumor"
- **THEN** the result reports count 1101 and total_in_manifest 1247

### Requirement: Single release instance per verification
All tools for one claim SHALL run against the same loaded TCGARelease instance, so repeated queries within a verification see identical data.

#### Scenario: Consistent results
- **WHEN** the verifier calls count_samples and then value_counts on clinical within the same verification
- **THEN** both results are computed from the same cached release frames
