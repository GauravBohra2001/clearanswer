"""Fast manifest lookups.

The sample_manifest is small (1,247 rows) and answers a surprisingly large
share of audit questions without touching the molecular files: how many
primary tumors, which samples have which layers, what's the slide count for a
case. ManifestTool exposes those queries cheaply.
"""
from __future__ import annotations

from core.loader import ALL_LAYER_FLAGS, TCGARelease


class ManifestTool:
    name = "manifest_lookup"

    description = (
        "Quick lookups against sample_manifest.csv and slide_manifest.csv. Use "
        "for cohort-level counts (how many primary tumors? how many have all "
        "five data layers?) and per-sample layer-availability checks — it "
        "avoids loading the molecular files.\n\n"
        "Actions:\n"
        "- count_samples: {action:'count_samples', sample_type?:'Primary Tumor'}\n"
        "- count_with_layers: {action:'count_with_layers', "
        "layers?:[has_survival,has_mutation,has_copy_number,has_rna,has_protein], "
        "sample_type?:'Primary Tumor'}\n"
        "- sample_info: {action:'sample_info', sample_id:'TCGA-...-01'}\n"
        "- layer_availability: {action:'layer_availability', "
        "sample_type?:'Primary Tumor'} — percent of samples with each layer.\n"
        "- has_all_layers: {action:'has_all_layers', sample_id:'TCGA-...-01'}\n"
    )

    def __init__(self, release: TCGARelease) -> None:
        self.release = release

    def execute(self, query: dict) -> dict:
        try:
            action = query.get("action")
            method = getattr(self, f"_a_{action}", None)
            if method is None:
                return {"ok": False, "error": f"unknown action {action!r}"}
            return method(query)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ------------------------------------------------------------------ actions

    def _a_count_samples(self, query: dict) -> dict:
        sm = self.release.load_layer("sample_manifest")
        st = query.get("sample_type")
        df = sm if not st else sm[sm["sample_type"] == st]
        return {
            "ok": True,
            "action": "count_samples",
            "sample_type": st,
            "count": int(len(df)),
            "total_in_manifest": int(len(sm)),
        }

    def _a_count_with_layers(self, query: dict) -> dict:
        sm = self.release.load_layer("sample_manifest")
        st = query.get("sample_type", "Primary Tumor")
        df = sm[sm["sample_type"] == st] if st else sm
        layers = query.get("layers") or list(ALL_LAYER_FLAGS)
        missing = [col for col in layers if col not in df.columns]
        if missing:
            raise KeyError(f"unknown layer flags: {missing}")
        mask = df[layers[0]].astype(bool).copy()
        for col in layers[1:]:
            mask &= df[col].astype(bool)
        return {
            "ok": True,
            "action": "count_with_layers",
            "sample_type": st,
            "layers_required": layers,
            "count": int(mask.sum()),
            "denominator": int(len(df)),
        }

    def _a_sample_info(self, query: dict) -> dict:
        sid = query.get("sample_id")
        if not sid:
            raise ValueError("missing 'sample_id'")
        sm = self.release.load_layer("sample_manifest")
        row = sm[sm["sample_id"] == sid]
        if row.empty:
            return {"ok": True, "action": "sample_info", "sample_id": sid, "found": False}
        rec = row.iloc[0].to_dict()
        return {
            "ok": True,
            "action": "sample_info",
            "sample_id": sid,
            "found": True,
            "record": {k: (int(v) if isinstance(v, bool) else v) for k, v in rec.items()},
        }

    def _a_layer_availability(self, query: dict) -> dict:
        sm = self.release.load_layer("sample_manifest")
        st = query.get("sample_type", "Primary Tumor")
        df = sm[sm["sample_type"] == st] if st else sm
        total = max(int(len(df)), 1)
        out = {}
        for col in ("in_clinical", *ALL_LAYER_FLAGS):
            n = int(df[col].astype(bool).sum())
            out[col] = {"n": n, "percent": round(100 * n / total, 1)}
        return {
            "ok": True,
            "action": "layer_availability",
            "sample_type": st,
            "denominator": total,
            "by_layer": out,
        }

    def _a_has_all_layers(self, query: dict) -> dict:
        sid = query.get("sample_id")
        if not sid:
            raise ValueError("missing 'sample_id'")
        sm = self.release.load_layer("sample_manifest")
        row = sm[sm["sample_id"] == sid]
        if row.empty:
            return {"ok": True, "action": "has_all_layers", "sample_id": sid, "found": False}
        r = row.iloc[0]
        all_true = all(bool(r[c]) for c in ALL_LAYER_FLAGS)
        return {
            "ok": True,
            "action": "has_all_layers",
            "sample_id": sid,
            "found": True,
            "all_layers_present": bool(all_true),
            "per_layer": {c: bool(r[c]) for c in ALL_LAYER_FLAGS},
        }
