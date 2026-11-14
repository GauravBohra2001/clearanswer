"""TCGA-BRCA data layer.

TCGARelease is the only thing that touches pandas. Agents call tools; tools
call this class. One instance holds a release directory (release A under
data/tcga-brca/raw/, or an envelope release under
envelopes/opened/<name>/release/) and caches each layer the first time it's
loaded.

Manifests (sample_manifest.csv, slide_manifest.csv) live one directory above
raw/, because they describe release-independent metadata.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import pandas as pd

LAYER_FILES: dict[str, str] = {
    "clinical": "clinical.tsv",
    "survival": "survival.tsv",
    "mutation": "mutation_gene_level.tsv.gz",
    "copy_number": "copy_number_gistic.tsv.gz",
    "protein": "protein_rppa.tsv.gz",
    "rna": "rna_hiseq.tsv.gz",
}

MANIFEST_FILES: dict[str, str] = {
    "sample_manifest": "sample_manifest.csv",
    "slide_manifest": "slide_manifest.csv",
}

# Molecular files are matrices with genes/proteins as rows and sample barcodes
# as columns. Clinical and survival are long tables keyed by sampleID.
MATRIX_LAYERS = {"mutation", "copy_number", "protein", "rna"}

# The five judged "data layers" per the TCGA-BRCA README. `in_clinical` is the
# base membership flag; the "all five layers" count is survival+mut+cn+rna+prot.
ALL_LAYER_FLAGS = ("has_survival", "has_mutation", "has_copy_number", "has_rna", "has_protein")


class TCGARelease:
    """A single TCGA-BRCA release directory, loaded on demand."""

    def __init__(self, release_dir: str | Path) -> None:
        self.release_dir = Path(release_dir).resolve()
        if not self.release_dir.exists():
            raise FileNotFoundError(f"release directory not found: {self.release_dir}")
        # Manifests sit one level up (data/tcga-brca/) for the raw release.
        # For envelope releases (envelopes/opened/<n>/release/), the manifests
        # are the same TCGA-wide tables — look them up in data/tcga-brca/.
        self.manifest_dir = self._find_manifest_dir()
        self._cache: dict[str, pd.DataFrame] = {}

    def _find_manifest_dir(self) -> Path:
        """Walk up until we find a directory containing sample_manifest.csv."""
        candidates = [self.release_dir.parent, self.release_dir]
        # Also try data/tcga-brca/ relative to the repo root.
        for ancestor in self.release_dir.parents:
            if (ancestor / "sample_manifest.csv").exists():
                return ancestor
            # Catch envelopes/opened/<n>/release/ → repo/data/tcga-brca/
            cand = ancestor.parent.parent / "data" / "tcga-brca"
            if cand.exists() and (cand / "sample_manifest.csv").exists():
                return cand
        for c in candidates:
            if (c / "sample_manifest.csv").exists():
                return c
        # Fall back to release_dir.parent even if missing — callers that need
        # manifests will get a clear FileNotFoundError.
        return self.release_dir.parent

    # ------------------------------------------------------------------ loading

    def _layer_path(self, name: str) -> Path:
        if name not in LAYER_FILES:
            raise KeyError(
                f"unknown layer {name!r}; known: {sorted(LAYER_FILES)}"
            )
        return self.release_dir / LAYER_FILES[name]

    def has_layer(self, name: str) -> bool:
        return name in LAYER_FILES and self._layer_path(name).exists()

    def load_layer(self, name: str) -> pd.DataFrame:
        if name in self._cache:
            return self._cache[name]
        if name in LAYER_FILES:
            path = self._layer_path(name)
            if not path.exists():
                raise FileNotFoundError(f"layer {name!r} missing: {path}")
            if name in MATRIX_LAYERS:
                df = pd.read_csv(path, sep="\t", index_col=0, low_memory=False)
            else:
                df = pd.read_csv(path, sep="\t", low_memory=False)
        elif name in MANIFEST_FILES:
            path = self.manifest_dir / MANIFEST_FILES[name]
            if not path.exists():
                raise FileNotFoundError(f"manifest {name!r} missing: {path}")
            df = pd.read_csv(path, low_memory=False)
        else:
            raise KeyError(
                f"unknown layer or manifest {name!r}; "
                f"known layers: {sorted(LAYER_FILES)}, "
                f"manifests: {sorted(MANIFEST_FILES)}"
            )
        self._cache[name] = df
        return df

    # --------------------------------------------------------------- selection

    def primary_tumors(self, layer_name: str) -> pd.DataFrame:
        """Return the layer filtered to primary-tumor samples.

        - For the sample_manifest, filter by sample_type == 'Primary Tumor'.
        - For clinical/survival (long tables keyed by sampleID), filter where
          the 15-character barcode's two-digit sample-type code is '01'.
        - For molecular matrices, filter columns whose barcode ends in '-01'.
        """
        df = self.load_layer(layer_name)
        if layer_name == "sample_manifest":
            return df[df["sample_type"] == "Primary Tumor"]
        if layer_name in ("clinical", "survival"):
            key = "sampleID" if "sampleID" in df.columns else "sample"
            return df[df[key].astype(str).str[13:15] == "01"]
        if layer_name in MATRIX_LAYERS:
            primary_cols = [c for c in df.columns if str(c)[13:15] == "01"]
            return df[primary_cols]
        return df

    # ----------------------------------------------------- reference analyses

    def count_primary_tumors(self) -> int:
        sm = self.load_layer("sample_manifest")
        return int((sm["sample_type"] == "Primary Tumor").sum())

    def count_with_all_layers(self) -> int:
        """Primary tumors with all 5 non-clinical layers present."""
        sm = self.load_layer("sample_manifest")
        primary = sm[sm["sample_type"] == "Primary Tumor"]
        mask = pd.Series(True, index=primary.index)
        for col in ALL_LAYER_FLAGS:
            mask &= primary[col].astype(bool)
        return int(mask.sum())

    def subtype_distribution(self) -> dict[str, int]:
        """PAM50 subtype counts for primary tumors with a subtype call."""
        clinical = self.load_layer("clinical")
        primary = clinical[clinical["sampleID"].astype(str).str[13:15] == "01"]
        called = primary.dropna(subset=["PAM50Call_RNAseq"])
        counts = called["PAM50Call_RNAseq"].value_counts().sort_index()
        return {str(k): int(v) for k, v in counts.items()}

    def er_status_distribution(self) -> dict[str, int]:
        """IHC ER status counts for primary tumors."""
        clinical = self.load_layer("clinical")
        primary = clinical[clinical["sampleID"].astype(str).str[13:15] == "01"]
        col = "breast_carcinoma_estrogen_receptor_status"
        counts = primary[col].dropna().value_counts()
        return {str(k): int(v) for k, v in counts.items()}

    def protein_by_er_status(self, protein: str = "ERALPHA") -> dict:
        """Reference analysis A1: mean RPPA of `protein` by clinical ER status."""
        clinical = self.load_layer("clinical")
        rppa = self.load_layer("protein")
        if protein not in rppa.index:
            raise KeyError(f"protein {protein!r} not in protein_rppa index")
        er = clinical.set_index("sampleID")["breast_carcinoma_estrogen_receptor_status"]
        samples = [
            s for s in rppa.columns
            if str(s)[13:15] == "01" and er.get(s) in ("Positive", "Negative")
        ]
        vals = rppa.loc[protein, samples]
        pos = vals[[s for s in samples if er[s] == "Positive"]]
        neg = vals[[s for s in samples if er[s] == "Negative"]]
        return {
            "protein": protein,
            "n_samples": len(samples),
            "n_positive": int(pos.size),
            "n_negative": int(neg.size),
            "mean_positive": round(float(pos.mean()), 3),
            "mean_negative": round(float(neg.mean()), 3),
            "difference": round(float(pos.mean() - neg.mean()), 3),
        }

    # -------------------------------------------------------------- utilities

    def get_column_info(self, layer_name: str) -> dict:
        """Column names, dtypes, non-null counts and sample values for a layer."""
        df = self.load_layer(layer_name)
        info = {"layer": layer_name, "n_rows": int(len(df)), "n_cols": int(len(df.columns)), "columns": []}
        # For molecular matrices, "columns" are sample barcodes — surface a few.
        for col in df.columns[:200]:
            series = df[col]
            info["columns"].append({
                "name": str(col),
                "dtype": str(series.dtype),
                "non_null": int(series.notna().sum()),
                "sample_values": [str(v) for v in series.dropna().head(3).tolist()],
            })
        if len(df.columns) > 200:
            info["truncated_after"] = 200
        return info

    def file_checksums(self) -> dict[str, str]:
        """SHA-256 of each layer file as downloaded (for audit.json `data`)."""
        out: dict[str, str] = {}
        for name, fname in LAYER_FILES.items():
            path = self._layer_path(name)
            if path.exists():
                out[fname] = _sha256(path)
        return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
