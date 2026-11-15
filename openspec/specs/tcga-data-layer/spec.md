# tcga-data-layer Specification

## Purpose
Load a frozen TCGA-BRCA release into pandas DataFrames with per-instance caching, filter layers to primary-tumor samples using the barcode sample-type code, and provide pure, deterministic primitives (counts, subtype distribution, layer overlap, column statistics) that the query tools and reference analyses build on. This is the only module in the system that touches pandas file I/O.

## Requirements

### Requirement: Release directory resolution
The system SHALL resolve a release from a raw data directory or an envelope path under `envelopes/opened/<n>/release/`, locating sample manifests by walking up ancestor directories until one contains `sample_manifest.csv`, with a fallback that maps an envelope's `release/` directory to the repository's `data/tcga-brca/` manifest location. A non-existent release directory SHALL raise FileNotFoundError at construction.

#### Scenario: Raw release
- **WHEN** TCGARelease is constructed with `.../data/tcga-brca/raw`
- **THEN** manifests are found in `.../data/tcga-brca/` (one level above raw) and layer files load from the raw directory

#### Scenario: Missing directory
- **WHEN** TCGARelease is constructed with a path that does not exist
- **THEN** construction raises FileNotFoundError naming the missing path

### Requirement: Layer and manifest loading with caching
The system SHALL expose six data layers (clinical, survival, mutation, copy_number, protein, rna) mapped to their exact file names and two manifests (sample_manifest, slide_manifest). Molecular matrices SHALL be read tab-separated with the first column as row index; long tables and manifests without an index. Each layer SHALL load at most once per instance and be cached thereafter. Unknown names SHALL raise KeyError listing the known layers and manifests; a missing file SHALL raise FileNotFoundError naming the expected path.

#### Scenario: Cached reload
- **WHEN** load_layer("clinical") is called twice on the same instance
- **THEN** the second call returns the cached DataFrame without re-reading the file

#### Scenario: Unknown layer name
- **WHEN** load_layer is called with a name that is neither a known layer nor a known manifest
- **THEN** a KeyError is raised listing the six known layers and two known manifests

### Requirement: Primary-tumor filtering by sample-type code
The system SHALL filter any layer to primary tumors using the sample-type code at barcode positions 13–15 ("01"): by the explicit `sample_type` column for the sample manifest, by the `sampleID`/`sample` column for clinical and survival tables, and by column barcodes for molecular matrices. Data-model primitives SHALL apply the same rule generically (Primary Tumor=01, Metastatic=06, Solid Tissue Normal=11), returning an empty frame for unrecognized types.

#### Scenario: Matrix filtering
- **WHEN** primary_tumors("rna") is called on a matrix whose columns are 15-character barcodes
- **THEN** only columns whose characters at positions 13–15 equal "01" remain, and all gene rows are preserved

#### Scenario: Unknown sample type in primitive
- **WHEN** count_samples is called with a sample_type not in the code table on a frame without a sample_type column
- **THEN** an empty result (count 0) is returned, not an exception

### Requirement: Reference cohort analyses
The system SHALL provide reference analyses computed directly from the release: primary-tumor count (1,101), count of primaries with all five non-clinical layer flags true (535), PAM50 subtype distribution over primaries with a non-null call (844 total; Luminal A largest at ~49.9%), IHC ER-status distribution for primaries, and mean RPPA protein expression by ER status (default ERALPHA) with per-group n, means to 3 decimals, and their difference.

#### Scenario: Five-layer overlap
- **WHEN** count_with_all_layers is called on the frozen release
- **THEN** it returns 535, the number of primary tumors whose has_survival, has_mutation, has_copy_number, has_rna, and has_protein flags are all true

#### Scenario: Protein by ER status
- **WHEN** protein_by_er_status is called for a protein present in the RPPA matrix
- **THEN** it returns n_samples, n_positive, n_negative, mean_positive, mean_negative (each rounded to 3 decimals), and difference, computed over primary samples with a Positive or Negative IHC ER status

### Requirement: Column introspection and file checksums
The system SHALL provide per-layer column info (name, dtype, non-null count, up to three sample values) for the first 200 columns with an explicit truncation marker when more exist, and SHALL compute SHA-256 checksums of each layer file as downloaded (read in 1 MB chunks) so the audit output can pin the exact data release used.

#### Scenario: Checksum block
- **WHEN** file_checksums is called on a complete release
- **THEN** it returns a mapping from each existing layer file name to its SHA-256 hex digest

### Requirement: Distribution and overlap primitives
The system SHALL compute subtype distributions as counts with percentages rounded to 1 decimal over non-null values only (matching the natural reading of "62% of primary tumors with an RNA subtype call"), and layer overlap as manifest rows where ALL requested flags are true, accepting 'rna' or 'has_rna' spelling and treating clinical/in_clinical as a synonym for the clinical membership flag.

#### Scenario: Percentage basis
- **WHEN** subtype_distribution is called on clinical with PAM50Call_RNAseq
- **THEN** percentages are computed over the non-null calls only, so they sum to approximately 100 across subtypes

#### Scenario: Layer name normalization
- **WHEN** layer_overlap is called with layers ["rna", "clinical"]
- **THEN** it resolves has_rna and in_clinical and returns manifest rows where both are true

### Requirement: Column inspection primitives
The system SHALL provide check_column_exists (case-sensitive), column_stats (numeric coercion with count/mean/median/min/max rounded to 2 decimals plus null_count; an all-zero/None shape for empty numeric columns; KeyError for missing columns), and get_column_values returning sorted unique non-null string values.

#### Scenario: Missing column stats
- **WHEN** column_stats is called for a column that does not exist
- **THEN** it raises KeyError naming the column
