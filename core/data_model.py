"""
Data model for TCGA-BRCA verification.
Every function is independently testable and deterministic.
The verifier agent maps claims to these functions via the semantic layer.

Note on sample_type filtering: our clinical.tsv does not carry a sample_type
column. Primary tumors are identified by the two-digit code at barcode
positions 13-15 (e.g. 'TCGA-3C-AAAU-01'). sample_manifest.csv does have an
explicit sample_type column. Functions here accept either shape; they filter
by sample_type when the column is present and by the barcode suffix otherwise.
"""
from __future__ import annotations

import pandas as pd

_SAMPLE_TYPE_CODE = {
    "Primary Tumor": "01",
    "Metastatic": "06",
    "Solid Tissue Normal": "11",
}


def _barcode_column(df: pd.DataFrame) -> str | None:
    for candidate in ("sampleID", "sample_id", "sample", "barcode"):
        if candidate in df.columns:
            return candidate
    return None


def _filter_by_sample_type(df: pd.DataFrame, sample_type: str) -> pd.DataFrame:
    """Filter a dataframe to one sample_type, whether the column is explicit
    (sample_manifest) or encoded in the barcode (clinical / survival)."""
    if "sample_type" in df.columns:
        return df[df["sample_type"] == sample_type]
    bc = _barcode_column(df)
    if not bc:
        return df
    code = _SAMPLE_TYPE_CODE.get(sample_type)
    if not code:
        return df.iloc[0:0]
    return df[df[bc].astype(str).str[13:15] == code]


def count_samples(df: pd.DataFrame, sample_type: str = "Primary Tumor") -> int:
    """Count rows for a given sample_type."""
    return int(len(_filter_by_sample_type(df, sample_type)))


def subtype_distribution(
    df: pd.DataFrame,
    column: str = "PAM50Call_RNAseq",
    sample_type: str = "Primary Tumor",
) -> tuple[pd.Series, pd.Series]:
    """Value counts and percentages for a categorical column.

    Returns (counts, percentages). Percentages are rounded to 1 decimal and
    computed over non-null values only, which matches the natural reading of
    claims like "62% of primary tumors with an RNA subtype call".
    """
    filtered = _filter_by_sample_type(df, sample_type)
    counts = filtered[column].dropna().value_counts()
    total = counts.sum()
    pcts = (counts / total * 100).round(1) if total else counts.astype(float)
    return counts, pcts


def layer_overlap(manifest: pd.DataFrame, layers: list[str]) -> pd.DataFrame:
    """Return manifest rows where ALL specified layer flags are True.

    `layers` may be written as 'has_rna' or 'rna'; the 'has_' prefix is added
    when missing. The column 'in_clinical' is accepted as a synonym for
    'has_clinical' so callers can treat clinical as just another layer.
    """
    bool_cols: list[str] = []
    for layer in layers:
        if layer == "has_clinical" or layer == "clinical":
            if "in_clinical" in manifest.columns:
                bool_cols.append("in_clinical")
                continue
            if "has_clinical" in manifest.columns:
                bool_cols.append("has_clinical")
                continue
            raise ValueError("neither in_clinical nor has_clinical present in manifest")
        col = layer if layer.startswith("has_") else f"has_{layer}"
        if col not in manifest.columns:
            raise ValueError(f"Unknown layer column: {col}")
        bool_cols.append(col)
    mask = manifest[bool_cols].astype(bool).all(axis=1)
    return manifest[mask]


def check_column_exists(df: pd.DataFrame, column: str) -> bool:
    """Case-sensitive check for whether a column exists in the dataframe."""
    return column in df.columns


def column_stats(
    df: pd.DataFrame,
    column: str,
    sample_type: str = "Primary Tumor",
) -> dict:
    """Basic stats for a numeric column, filtered by sample_type when possible."""
    filtered = _filter_by_sample_type(df, sample_type)
    if column not in filtered.columns:
        raise KeyError(f"column {column!r} not in dataframe")
    series = pd.to_numeric(filtered[column], errors="coerce").dropna()
    if series.empty:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None,
                "null_count": int(filtered[column].isna().sum())}
    return {
        "count": int(len(series)),
        "mean": round(float(series.mean()), 2),
        "median": round(float(series.median()), 2),
        "min": round(float(series.min()), 2),
        "max": round(float(series.max()), 2),
        "null_count": int(filtered[column].isna().sum()),
    }


def get_column_values(
    df: pd.DataFrame,
    column: str,
    sample_type: str = "Primary Tumor",
) -> list:
    """Unique non-null values for a column, filtered by sample_type."""
    filtered = _filter_by_sample_type(df, sample_type)
    return sorted(filtered[column].dropna().astype(str).unique().tolist())
