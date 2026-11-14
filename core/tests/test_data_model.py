"""
Unit tests for data_model.py, run against the actual TCGA-BRCA data.
These prove the data layer is deterministic and correct.

Default data dir points at oncosys-hackathon-challenge/data/tcga-brca so the
tests work out of the box after `python data/tcga-brca/fetch.py`. Override
with the TCGA_DATA_DIR environment variable to point elsewhere (an envelope
release, a different fetch, etc.) - raw files are read from <DIR>/raw and the
manifests from <DIR> itself.
"""
from __future__ import annotations

import os
import pathlib

import pandas as pd
import pytest

from core.data_model import (
    check_column_exists,
    column_stats,
    count_samples,
    layer_overlap,
    subtype_distribution,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "oncosys-hackathon-challenge" / "data" / "tcga-brca"
DATA_DIR = pathlib.Path(os.environ.get("TCGA_DATA_DIR", str(DEFAULT_DATA_DIR)))


@pytest.fixture
def clinical() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "raw" / "clinical.tsv", sep="\t", low_memory=False)


@pytest.fixture
def manifest() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "sample_manifest.csv", low_memory=False)


class TestCountSamples:
    def test_primary_tumor_count_via_manifest(self, manifest):
        count = count_samples(manifest, "Primary Tumor")
        assert count == 1101, f"Expected 1101 primary tumors, got {count}"

    def test_primary_tumor_count_via_clinical_barcode(self, clinical):
        # clinical.tsv has no sample_type column; falls back to barcode position.
        count = count_samples(clinical, "Primary Tumor")
        assert count == 1101, f"Expected 1101 primary tumors from clinical, got {count}"

    def test_returns_int(self, manifest):
        assert isinstance(count_samples(manifest, "Primary Tumor"), int)


class TestSubtypeDistribution:
    def test_luma_is_largest(self, clinical):
        counts, _ = subtype_distribution(clinical)
        assert counts.index[0] == "LumA", f"Expected LumA as largest, got {counts.index[0]}"

    def test_luma_percentage_is_not_62(self, clinical):
        _, pcts = subtype_distribution(clinical)
        assert abs(pcts["LumA"] - 49.9) < 1.0, f"LumA should be ~49.9%, got {pcts['LumA']}"

    def test_all_subtypes_present(self, clinical):
        counts, _ = subtype_distribution(clinical)
        expected = {"LumA", "LumB", "Basal", "Her2", "Normal"}
        assert set(counts.index) == expected

    def test_percentages_sum_to_100(self, clinical):
        _, pcts = subtype_distribution(clinical)
        assert abs(pcts.sum() - 100.0) < 0.5, f"Percentages sum to {pcts.sum()}"


class TestLayerOverlap:
    def test_five_layer_overlap(self, manifest):
        result = layer_overlap(
            manifest,
            ["has_survival", "has_mutation", "has_copy_number", "has_rna", "has_protein"],
        )
        primary = result[result["sample_type"] == "Primary Tumor"]
        assert len(primary) == 535, f"Expected 535 primary tumors with all 5 layers, got {len(primary)}"

    def test_invalid_layer_raises(self, manifest):
        with pytest.raises(ValueError):
            layer_overlap(manifest, ["has_nonexistent"])

    def test_bare_name_accepted(self, manifest):
        a = layer_overlap(manifest, ["has_rna", "has_protein"])
        b = layer_overlap(manifest, ["rna", "protein"])
        assert len(a) == len(b)

    def test_clinical_synonym(self, manifest):
        a = layer_overlap(manifest, ["clinical"])
        assert len(a) == int(manifest["in_clinical"].astype(bool).sum())


class TestCheckColumnExists:
    def test_existing_column(self, clinical):
        assert check_column_exists(clinical, "PAM50Call_RNAseq") is True

    def test_missing_column(self, clinical):
        assert check_column_exists(clinical, "hormone_therapy") is False

    def test_missing_treatment_response(self, clinical):
        assert check_column_exists(clinical, "treatment_response") is False


class TestColumnStats:
    def test_age_stats(self, clinical):
        stats = column_stats(clinical, "age_at_initial_pathologic_diagnosis", "Primary Tumor")
        assert stats["count"] > 500
        assert 20 <= stats["min"] <= 50
        assert 70 <= stats["max"] <= 100
        assert 50 <= stats["mean"] <= 65

    def test_missing_column_raises(self, clinical):
        with pytest.raises(KeyError):
            column_stats(clinical, "nonexistent_col", "Primary Tumor")
