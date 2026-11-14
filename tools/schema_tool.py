"""Schema-introspection tool.

Before an agent can run data_query, it needs to know which columns exist and
what they contain. SchemaTool exposes that in small, cheap calls — no row
scans, just column metadata.

search_columns is the key action for the Claim Auditor: when a claim mentions
"hormone therapy response" or "survival", the agent searches column names
across layers to find candidates before asserting the data can or can't answer.
"""
from __future__ import annotations

import pandas as pd

from core.loader import LAYER_FILES, MANIFEST_FILES, TCGARelease

_LAYER_NAMES = sorted(list(LAYER_FILES.keys()) + list(MANIFEST_FILES.keys()))


class SchemaTool:
    name = "schema_info"

    description = (
        "Inspect the shape and columns of a TCGA-BRCA data layer without "
        "loading any rows beyond what's needed. Call this BEFORE data_query "
        "when you aren't sure which columns exist, or whether a concept "
        "(e.g. 'hormone therapy response') is captured by the data.\n\n"
        f"Layers: {_LAYER_NAMES}.\n\n"
        "Actions:\n"
        "- list_layers: no args — list available layers and manifests.\n"
        "- columns:        {action:'columns', layer}  — column names only.\n"
        "- dtypes:         {action:'dtypes', layer}   — column name + dtype.\n"
        "- sample_values:  {action:'sample_values', layer, column, n?:5}\n"
        "- unique_values:  {action:'unique_values', layer, column, limit?:50}\n"
        "- describe_column:{action:'describe_column', layer, column}\n"
        "- search_columns: {action:'search_columns', layer?, query} — "
        "substring search across column names in one or every layer.\n"
    )

    def __init__(self, release: TCGARelease) -> None:
        self.release = release

    def execute(self, query: dict) -> dict:
        try:
            action = query.get("action", "list_layers")
            method = getattr(self, f"_a_{action}", None)
            if method is None:
                return {"ok": False, "error": f"unknown action {action!r}"}
            return method(query)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ------------------------------------------------------------------ actions

    def _a_list_layers(self, _query: dict) -> dict:
        return {
            "ok": True,
            "action": "list_layers",
            "layers": sorted(LAYER_FILES),
            "manifests": sorted(MANIFEST_FILES),
        }

    def _a_columns(self, query: dict) -> dict:
        layer = self._require(query, "layer")
        df = self.release.load_layer(layer)
        cols = [str(c) for c in df.columns]
        return {
            "ok": True,
            "action": "columns",
            "layer": layer,
            "n_columns": len(cols),
            "columns": cols[:500],
            "truncated": len(cols) > 500,
        }

    def _a_dtypes(self, query: dict) -> dict:
        layer = self._require(query, "layer")
        df = self.release.load_layer(layer)
        items = [(str(c), str(df[c].dtype)) for c in df.columns[:500]]
        return {
            "ok": True,
            "action": "dtypes",
            "layer": layer,
            "dtypes": dict(items),
            "truncated": len(df.columns) > 500,
        }

    def _a_sample_values(self, query: dict) -> dict:
        layer = self._require(query, "layer")
        column = self._require(query, "column")
        df = self.release.load_layer(layer)
        if column not in df.columns:
            raise KeyError(f"column {column!r} not in layer {layer!r}")
        n = int(query.get("n", 5))
        series = df[column].dropna()
        return {
            "ok": True,
            "action": "sample_values",
            "layer": layer,
            "column": column,
            "values": [str(v) for v in series.head(n).tolist()],
        }

    def _a_unique_values(self, query: dict) -> dict:
        layer = self._require(query, "layer")
        column = self._require(query, "column")
        df = self.release.load_layer(layer)
        if column not in df.columns:
            raise KeyError(f"column {column!r} not in layer {layer!r}")
        limit = int(query.get("limit", 50))
        vals = df[column].dropna().unique().tolist()
        return {
            "ok": True,
            "action": "unique_values",
            "layer": layer,
            "column": column,
            "n_unique": len(vals),
            "values": [str(v) for v in vals[:limit]],
            "truncated": len(vals) > limit,
        }

    def _a_describe_column(self, query: dict) -> dict:
        layer = self._require(query, "layer")
        column = self._require(query, "column")
        df = self.release.load_layer(layer)
        if column not in df.columns:
            raise KeyError(f"column {column!r} not in layer {layer!r}")
        series = df[column]
        numeric = pd.to_numeric(series, errors="coerce").dropna()
        info = {
            "layer": layer,
            "column": column,
            "dtype": str(series.dtype),
            "n_rows": int(len(series)),
            "non_null": int(series.notna().sum()),
            "null": int(series.isna().sum()),
            "n_unique": int(series.nunique(dropna=True)),
        }
        if numeric.size:
            info["numeric_summary"] = {
                "min": float(numeric.min()),
                "max": float(numeric.max()),
                "mean": float(numeric.mean()),
                "median": float(numeric.median()),
            }
        else:
            info["top_values"] = {
                str(k): int(v) for k, v in series.value_counts().head(10).items()
            }
        return {"ok": True, "action": "describe_column", **info}

    def _a_search_columns(self, query: dict) -> dict:
        needle = self._require(query, "query").lower().strip()
        layer = query.get("layer")
        layers = [layer] if layer else sorted(LAYER_FILES) + sorted(MANIFEST_FILES)
        hits: dict[str, list[str]] = {}
        for lname in layers:
            try:
                df = self.release.load_layer(lname)
            except FileNotFoundError:
                continue
            matches = [str(c) for c in df.columns if needle in str(c).lower()]
            if matches:
                hits[lname] = matches[:200]
        return {
            "ok": True,
            "action": "search_columns",
            "query": needle,
            "matches_by_layer": hits,
            "n_hits": sum(len(v) for v in hits.values()),
        }

    @staticmethod
    def _require(query: dict, key: str) -> str:
        value = query.get(key)
        if value in (None, ""):
            raise ValueError(f"missing required field {key!r}")
        return value
