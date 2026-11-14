"""
Semantic layer for TCGA-BRCA dataset.
Maps dataset structure to operations the verifier can use.
Swap this file to support a different dataset (TCGA-LUAD, TCGA-PRAD, etc.)

The column and file names here match the files produced by
oncosys-hackathon-challenge/data/tcga-brca/fetch.py as processed by the
UCSC Xena hub. If a column is listed but not present, the verifier will
discover that at query time via the real pandas call.
"""
from __future__ import annotations

TCGA_BRCA_SCHEMA = {
    "dataset": "TCGA-BRCA",
    "description": (
        "Breast cancer cohort from The Cancer Genome Atlas. 1,247 samples "
        "in sample_manifest.csv, of which 1,101 are primary tumors, 139 "
        "normal tissue, and 7 metastatic. Six data layers: clinical, "
        "survival, mutation, copy number, RNA, protein. 535 primary tumors "
        "have all 5 non-clinical layers."
    ),
    "tables": {
        "clinical": {
            "file": "clinical.tsv",
            "description": (
                "One row per sample. Demographics, diagnosis, molecular "
                "subtypes. Keyed by sampleID (15-char barcode). "
                "Primary tumors are sampleIDs where positions 13-15 are '01'."
            ),
            "key_column": "sampleID",
            "primary_tumor_predicate": "sampleID.str[13:15] == '01'",
            "columns": {
                "sampleID": {
                    "description": "TCGA sample barcode, 15 characters.",
                    "dtype": "string",
                    "use_for": ["joining tables", "identifying primary tumors"],
                },
                "PAM50Call_RNAseq": {
                    "description": "PAM50 RNA-based molecular subtype call.",
                    "dtype": "categorical",
                    "values": ["LumA", "LumB", "Basal", "Her2", "Normal"],
                    "use_for": [
                        "subtype distribution",
                        "largest subtype",
                        "subtype percentages",
                        "molecular subtype",
                        "rna subtype",
                    ],
                    "null_note": (
                        "257 of 1,101 primary tumors lack this call. Compute "
                        "percentages over the 844 with a non-null call."
                    ),
                },
                "breast_carcinoma_estrogen_receptor_status": {
                    "description": "ER status by IHC.",
                    "dtype": "categorical",
                    "values": ["Positive", "Negative", "Indeterminate"],
                    "use_for": [
                        "ER status filtering",
                        "estrogen receptor",
                        "receptor status",
                    ],
                },
                "breast_carcinoma_progesterone_receptor_status": {
                    "description": "PR status by IHC.",
                    "dtype": "categorical",
                    "values": ["Positive", "Negative", "Indeterminate"],
                    "use_for": [
                        "PR status filtering",
                        "progesterone receptor",
                        "receptor status",
                    ],
                },
                "her2_immunohistochemistry_level_result": {
                    "description": "HER2 level by IHC (0, 1+, 2+, 3+).",
                    "dtype": "categorical",
                    "use_for": [
                        "HER2 status filtering",
                        "her2 receptor",
                        "receptor status",
                    ],
                },
                "histological_type": {
                    "description": "Histological classification of tumor.",
                    "dtype": "categorical",
                    "use_for": ["histology distribution"],
                },
                "age_at_initial_pathologic_diagnosis": {
                    "description": "Patient age at initial diagnosis in years.",
                    "dtype": "numeric",
                    "use_for": ["age statistics", "age distribution"],
                },
                "radiation_therapy": {
                    "description": (
                        "Whether patient received radiation therapy (YES/NO "
                        "flag only, no response data)."
                    ),
                    "dtype": "categorical",
                    "values": ["YES", "NO"],
                    "use_for": ["treatment flag only"],
                    "limitation": (
                        "Records whether therapy was given, NOT treatment "
                        "response or outcome."
                    ),
                },
                "targeted_molecular_therapy": {
                    "description": (
                        "Whether patient received targeted molecular therapy "
                        "(YES/NO flag only)."
                    ),
                    "dtype": "categorical",
                    "values": ["YES", "NO"],
                    "use_for": ["treatment flag only"],
                    "limitation": (
                        "Records whether therapy was given, NOT treatment "
                        "response or outcome."
                    ),
                },
                "additional_pharmaceutical_therapy": {
                    "description": (
                        "Whether patient received additional pharmaceutical "
                        "therapy (YES/NO flag only)."
                    ),
                    "dtype": "categorical",
                    "values": ["YES", "NO"],
                    "use_for": ["treatment flag only"],
                    "limitation": (
                        "Records whether therapy was given, NOT treatment "
                        "response or outcome."
                    ),
                },
            },
            "does_not_have": [
                "hormone_therapy",
                "hormone_therapy_response",
                "endocrine_therapy",
                "endocrine_response",
                "treatment_response",
                "therapy_response",
                "pathological_response",
                "drug_name",
                "drug_efficacy",
                "chemotherapy_response",
                "tamoxifen",
                "aromatase_inhibitor",
                "responder",
                "best_responder",
            ],
        },
        "survival": {
            "file": "survival.tsv",
            "description": (
                "Overall survival and vital status per patient. Observational "
                "only, not from a treatment trial."
            ),
            "key_column": "sample",
            "columns": {
                "OS": {
                    "description": "Overall survival event indicator: 1=death, 0=censored.",
                    "dtype": "numeric",
                },
                "OS.time": {
                    "description": "Overall survival time in days.",
                    "dtype": "numeric",
                },
                "_PATIENT": {
                    "description": "Patient barcode for joining.",
                    "dtype": "string",
                },
            },
            "limitations": [
                "Observational survival only. No treatment response data.",
                "Cannot determine whether treatment caused survival differences.",
            ],
        },
        "sample_manifest": {
            "file": "sample_manifest.csv",
            "description": (
                "One row per sample. Lists the barcode, sample_type, and "
                "boolean flags for which data layers that sample has."
            ),
            "key_column": "sample_id",
            "columns": {
                "sample_id": {"description": "TCGA sample barcode.", "dtype": "string"},
                "patient_id": {"description": "TCGA patient barcode.", "dtype": "string"},
                "sample_type": {
                    "description": "One of 'Primary Tumor', 'Solid Tissue Normal', 'Metastatic'.",
                    "dtype": "categorical",
                    "values": ["Primary Tumor", "Solid Tissue Normal", "Metastatic"],
                    "use_for": [
                        "filtering primary tumors",
                        "sample counts",
                        "cohort size",
                    ],
                },
                "in_clinical": {"description": "Sample has a row in clinical.tsv.", "dtype": "boolean"},
                "has_survival": {"description": "Sample has survival data.", "dtype": "boolean"},
                "has_mutation": {"description": "Sample has gene-level mutation data.", "dtype": "boolean"},
                "has_copy_number": {"description": "Sample has GISTIC copy number data.", "dtype": "boolean"},
                "has_rna": {"description": "Sample has RNA HiSeq expression data.", "dtype": "boolean"},
                "has_protein": {"description": "Sample has RPPA protein data.", "dtype": "boolean"},
                "slides_for_sample": {"description": "Count of slides linked in IDC.", "dtype": "numeric"},
            },
            "use_for": [
                "layer overlap counts",
                "multi-omic sample counts",
                "primary tumor count",
            ],
        },
        "protein_rppa": {
            "file": "protein_rppa.tsv.gz",
            "description": (
                "Reverse Phase Protein Array data. Rows are antibody / "
                "protein names (131 in this release), columns are sample "
                "barcodes (747 samples)."
            ),
            "use_for": ["protein expression levels", "ER-alpha protein", "HER2 protein"],
            "does_not_have": ["treatment_response", "drug_response", "therapy_outcome"],
        },
        "mutation_gene_level": {
            "file": "mutation_gene_level.tsv.gz",
            "description": "Binary gene-level mutation calls (MC3). 1=mutated, 0=wild-type.",
            "use_for": ["mutation status", "mutation frequency"],
        },
        "rna_hiseq": {
            "file": "rna_hiseq.tsv.gz",
            "description": "RNA-seq gene expression (HiSeq), log2 RSEM values.",
            "use_for": ["gene expression levels", "expression comparisons"],
        },
        "copy_number_gistic": {
            "file": "copy_number_gistic.tsv.gz",
            "description": "GISTIC2 thresholded copy number. -2 deep del, -1 shallow del, 0 diploid, 1 gain, 2 amplification.",
            "use_for": ["copy number status", "amplification", "deletion"],
        },
    },
    "operations": {
        "count_samples": {
            "description": "Count rows matching a sample_type filter (e.g. count primary tumors).",
            "function": "count_samples",
            "args": ["df", "sample_type"],
        },
        "distribution": {
            "description": "Value counts and percentages for a categorical column.",
            "function": "subtype_distribution",
            "args": ["df", "column", "sample_type"],
        },
        "layer_overlap": {
            "description": "Count manifest rows that have ALL specified data layers.",
            "function": "layer_overlap",
            "args": ["manifest", "layers"],
        },
        "check_column_exists": {
            "description": "Check whether a column or data field exists in a table.",
            "function": "check_column_exists",
            "args": ["df", "column"],
        },
        "column_stats": {
            "description": "Basic statistics (mean, median, min, max) for a numeric column.",
            "function": "column_stats",
            "args": ["df", "column", "sample_type"],
        },
    },
    "cannot_answer": [
        {
            "topic": "treatment response",
            "reason": (
                "No treatment outcome or response data in TCGA-BRCA. The "
                "clinical table only has yes/no flags for whether radiation, "
                "targeted molecular, or additional pharmaceutical therapy was "
                "given, and no response or outcome field for any of them."
            ),
        },
        {
            "topic": "drug efficacy",
            "reason": "Observational cohort, not a clinical trial. No drug-response endpoints.",
        },
        {
            "topic": "hormone therapy",
            "reason": (
                "No hormone-therapy or endocrine-therapy column exists in "
                "clinical.tsv. Available therapy fields are radiation_therapy, "
                "targeted_molecular_therapy, and additional_pharmaceutical_therapy "
                "(all YES/NO flags only, no response measure). Verifying "
                "hormone therapy claims would require METABRIC or a "
                "neo-adjuvant endocrine therapy trial."
            ),
        },
        {
            "topic": "endocrine therapy",
            "reason": "Same as hormone therapy: not recorded in TCGA-BRCA.",
        },
        {
            "topic": "responded best",
            "reason": "No treatment-response data in TCGA-BRCA.",
        },
        {
            "topic": "protein-treatment correlation",
            "reason": (
                "Protein data (RPPA) exists but no treatment-response data to "
                "correlate against."
            ),
        },
        {
            "topic": "causal",
            "reason": (
                "Cross-sectional observational data only. Cannot establish "
                "causation from TCGA-BRCA."
            ),
        },
    ],
}


def get_schema() -> dict:
    """Return the schema for use in prompts."""
    return TCGA_BRCA_SCHEMA


def find_table_for_claim(claim_text: str) -> list[str]:
    """Return table names that might be relevant to a claim, based on use_for fields."""
    claim_lower = claim_text.lower()
    relevant: list[str] = []
    for table_name, table_info in TCGA_BRCA_SCHEMA["tables"].items():
        if "use_for" in table_info:
            for use in table_info["use_for"]:
                if any(word in claim_lower for word in use.lower().split()):
                    relevant.append(table_name)
                    break
        if "columns" in table_info:
            for _, col_info in table_info["columns"].items():
                if isinstance(col_info, dict) and "use_for" in col_info:
                    for use in col_info["use_for"]:
                        if any(word in claim_lower for word in use.lower().split()):
                            if table_name not in relevant:
                                relevant.append(table_name)
                            break
    return relevant


def check_cannot_answer(claim_text: str) -> dict | None:
    """Check if a claim falls into the cannot_answer category.

    Returns the matching entry when a topic phrase (all words) appears in
    the claim, or when a word in a does_not_have list appears. Returns None
    when the claim can be checked against the data.
    """
    if not claim_text:
        return None
    claim_lower = claim_text.lower()
    for entry in TCGA_BRCA_SCHEMA["cannot_answer"]:
        topic_words = entry["topic"].lower().split()
        if all(word in claim_lower for word in topic_words):
            return entry
    for table_name, table_info in TCGA_BRCA_SCHEMA["tables"].items():
        if "does_not_have" in table_info:
            for missing in table_info["does_not_have"]:
                needle = missing.replace("_", " ")
                if needle in claim_lower or missing in claim_lower:
                    return {
                        "topic": missing,
                        "reason": (
                            f"{table_name} ({table_info['file']}) does not have "
                            f"'{missing}'. See does_not_have list in the schema."
                        ),
                    }
    return None


def get_schema_summary_for_prompt() -> str:
    """Compact plain-text summary of the schema for inclusion in LLM prompts."""
    lines = [
        f"Dataset: {TCGA_BRCA_SCHEMA['dataset']}",
        f"Description: {TCGA_BRCA_SCHEMA['description']}",
        "",
        "Tables:",
    ]
    for table_name, table_info in TCGA_BRCA_SCHEMA["tables"].items():
        lines.append(f"  {table_name} ({table_info['file']}): {table_info['description']}")
        if "columns" in table_info:
            for col_name, col_info in table_info["columns"].items():
                if not isinstance(col_info, dict):
                    continue
                desc = col_info.get("description", "")
                values = col_info.get("values", [])
                val_str = f" Values: {values}" if values else ""
                lim = col_info.get("limitation", "")
                lim_str = f" LIMITATION: {lim}" if lim else ""
                lines.append(f"    - {col_name}: {desc}{val_str}{lim_str}")
        if "does_not_have" in table_info:
            lines.append(f"    DOES NOT HAVE: {', '.join(table_info['does_not_have'])}")
        if "limitations" in table_info:
            for lim in table_info["limitations"]:
                lines.append(f"    LIMITATION: {lim}")
    lines.append("")
    lines.append("Available operations: " + ", ".join(TCGA_BRCA_SCHEMA["operations"].keys()))
    lines.append("")
    lines.append("CANNOT ANSWER:")
    for entry in TCGA_BRCA_SCHEMA["cannot_answer"]:
        lines.append(f"  - {entry['topic']}: {entry['reason']}")
    return "\n".join(lines)
