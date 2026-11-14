"""The agent's primary data-query tool.

The agent decides *what* to compute (count ER-positive primary tumors,
describe the ERALPHA RPPA column, etc.); this tool decides *how* to compute it
deterministically with pandas. "Ground truth from the environment" - the LLM
never produces a number, it asks this tool for one.

Supported operations
--------------------
count         rows (optionally after a filter)
filter        return rows matching conditions (row_count + head preview)
aggregate     mean/sum/min/max/median of a numeric column, optionally grouped
value_counts  distribution of a categorical column
describe      summary statistics for a column (numeric or categorical)
compare       two aggregates in one call (e.g. mean by group A vs group B)
unique        unique values in a column (capped sample)

Every result carries source_file and query_description so the agent can cite it.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from core.loader import LAYER_FILES, MANIFEST_FILES, MATRIX_LAYERS, TCGARelease


_LAYER_NAMES = sorted(list(LAYER_FILES.keys()) + list(MANIFEST_FILES.keys()))


class DataTool:
    """Executes pandas queries against a TCGARelease."""

    name = "data_query"

    description = (
        "Run a deterministic pandas query against a loaded TCGA-BRCA data layer "
        "and return the exact numbers. Use this whenever you need a count, a "
        "mean, a value_counts distribution, or a comparison between groups - "
        "do not estimate numbers from memory.\n\n"
        f"Layers available: {_LAYER_NAMES}.\n"
        "- 'sample_manifest' / 'slide_manifest' are the small TCGA-wide tables.\n"
        "- 'clinical' / 'survival' are long tables keyed by sampleID "
        "(TCGA-XX-XXXX-01 for primary tumors).\n"
        "- 'mutation' / 'copy_number' / 'protein' / 'rna' are matrices with "
        "genes or proteins as the row index and sample barcodes as columns.\n\n"
        "Operations:\n"
        "- count: {operation: 'count', layer, filter?: {column: value}, primary_only?: bool}\n"
        "- filter: {operation: 'filter', layer, where: {col: value|{op:'>=',value:N}}, "
        "columns?: [..], limit?: int}\n"
        "- aggregate: {operation: 'aggregate', layer, column, agg: 'mean|sum|min|max|median', "
        "group_by?: col}\n"
        "- value_counts: {operation: 'value_counts', layer, column, primary_only?: bool, "
        "dropna?: bool}\n"
        "- describe: {operation: 'describe', layer, column}\n"
        "- compare: {operation: 'compare', layer, column, group_by, agg:'mean|median'}\n"
        "- unique: {operation: 'unique', layer, column, limit?: int}\n\n"
        "Example - PAM50 subtype distribution of primary tumors:\n"
        "  {operation: 'value_counts', layer: 'clinical', column: 'PAM50Call_RNAseq', "
        "primary_only: true}\n"
    )

    def __init__(self, release: TCGARelease) -> None:
        self.release = release

    # ---------------------------------------------------------- tool-use schema

    def schema(self) -> dict:
        """JSON schema for Anthropic tool_use input_schema."""
        return {
            "type": "object",
            "required": ["operation", "layer"],
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["count", "filter", "aggregate", "value_counts",
                             "describe", "compare", "unique"],
                },
                "layer": {"type": "string", "enum": _LAYER_NAMES},
                "column": {"type": "string"},
                "columns": {"type": "array", "items": {"type": "string"}},
                "where": {"type": "object"},
                "filter": {"type": "object"},
                "agg": {
                    "type": "string",
                    "enum": ["mean", "sum", "min", "max", "median", "count"],
                },
                "group_by": {"type": "string"},
                "primary_only": {"type": "boolean"},
                "dropna": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
        }

    # --------------------------------------------------------------- execution

    def execute(self, query: dict) -> dict:
        try:
            op = query.get("operation")
            layer = query.get("layer")
            if not op:
                return self._err("missing 'operation'", query)
            if not layer:
                return self._err("missing 'layer'", query)
            if layer not in _LAYER_NAMES:
                return self._err(
                    f"unknown layer {layer!r}; available: {_LAYER_NAMES}", query
                )
            df = self._select(layer, query)
            method = getattr(self, f"_op_{op}", None)
            if method is None:
                return self._err(f"unknown operation {op!r}", query)
            result = method(df, query)
            source = LAYER_FILES.get(layer, MANIFEST_FILES.get(layer, layer))
            return {
                "ok": True,
                "operation": op,
                "layer": layer,
                "source_file": source,
                "query_description": _describe(query),
                **result,
            }
        except Exception as e:  # noqa: BLE001 - surfaced to the agent
            return self._err(f"{type(e).__name__}: {e}", query)

    # --------------------------------------------------------------- selectors

    def _select(self, layer: str, query: dict) -> pd.DataFrame:
        if query.get("primary_only"):
            return self.release.primary_tumors(layer)
        return self.release.load_layer(layer)

    @staticmethod
    def _apply_where(df: pd.DataFrame, where: dict) -> pd.DataFrame:
        if not where:
            return df
        out = df
        for col, cond in where.items():
            if col not in out.columns:
                raise KeyError(f"column {col!r} not in layer (have: {list(out.columns)[:20]}…)")
            if isinstance(cond, dict) and "op" in cond and "value" in cond:
                op, val = cond["op"], cond["value"]
                series = out[col]
                if op == "==":
                    out = out[series == val]
                elif op == "!=":
                    out = out[series != val]
                elif op == ">":
                    out = out[series > val]
                elif op == ">=":
                    out = out[series >= val]
                elif op == "<":
                    out = out[series < val]
                elif op == "<=":
                    out = out[series <= val]
                elif op == "in":
                    out = out[series.isin(val)]
                elif op == "not_in":
                    out = out[~series.isin(val)]
                else:
                    raise ValueError(f"unknown operator {op!r}")
            else:
                out = out[out[col] == cond]
        return out

    # ------------------------------------------------------------- operations

    def _op_count(self, df: pd.DataFrame, query: dict) -> dict:
        where = query.get("where") or query.get("filter") or {}
        df = self._apply_where(df, where)
        return {"result": int(len(df)), "row_count": int(len(df))}

    def _op_filter(self, df: pd.DataFrame, query: dict) -> dict:
        where = query.get("where") or query.get("filter") or {}
        df = self._apply_where(df, where)
        cols = query.get("columns")
        if cols:
            missing = [c for c in cols if c not in df.columns]
            if missing:
                raise KeyError(f"columns not in layer: {missing}")
            df = df[cols]
        limit = int(query.get("limit") or 25)
        preview = df.head(limit).astype(object).where(df.head(limit).notna(), None).to_dict(orient="records")
        return {"result": preview, "row_count": int(len(df))}

    def _op_aggregate(self, df: pd.DataFrame, query: dict) -> dict:
        column = query["column"]
        agg = query.get("agg", "mean")
        if column not in df.columns:
            raise KeyError(f"column {column!r} not in layer")
        group_by = query.get("group_by")
        if group_by:
            if group_by not in df.columns:
                raise KeyError(f"group_by column {group_by!r} not in layer")
            series = pd.to_numeric(df[column], errors="coerce")
            grouped = series.groupby(df[group_by]).agg(agg)
            return {
                "result": {str(k): _num(v) for k, v in grouped.items()},
                "row_count": int(series.notna().sum()),
            }
        series = pd.to_numeric(df[column], errors="coerce").dropna()
        value = getattr(series, agg)()
        return {"result": _num(value), "row_count": int(series.size)}

    def _op_value_counts(self, df: pd.DataFrame, query: dict) -> dict:
        column = query["column"]
        if column not in df.columns:
            raise KeyError(f"column {column!r} not in layer")
        dropna = bool(query.get("dropna", True))
        counts = df[column].value_counts(dropna=dropna)
        total = int(counts.sum())
        return {
            "result": {str(k): int(v) for k, v in counts.items()},
            "row_count": int(len(df)),
            "total_counted": total,
            "percent": {str(k): round(100 * int(v) / total, 2) for k, v in counts.items()} if total else {},
        }

    def _op_describe(self, df: pd.DataFrame, query: dict) -> dict:
        column = query["column"]
        if column not in df.columns:
            raise KeyError(f"column {column!r} not in layer")
        series = df[column]
        numeric = pd.to_numeric(series, errors="coerce").dropna()
        result: dict[str, Any] = {
            "dtype": str(series.dtype),
            "non_null": int(series.notna().sum()),
            "null": int(series.isna().sum()),
            "n_unique": int(series.nunique(dropna=True)),
        }
        if numeric.size:
            result.update({
                "numeric": True,
                "mean": _num(numeric.mean()),
                "std": _num(numeric.std()),
                "min": _num(numeric.min()),
                "max": _num(numeric.max()),
                "median": _num(numeric.median()),
            })
        else:
            result.update({
                "numeric": False,
                "top_values": {str(k): int(v) for k, v in series.value_counts().head(10).items()},
            })
        return {"result": result, "row_count": int(len(df))}

    def _op_compare(self, df: pd.DataFrame, query: dict) -> dict:
        column = query["column"]
        group_by = query["group_by"]
        agg = query.get("agg", "mean")
        if column not in df.columns:
            raise KeyError(f"column {column!r} not in layer")
        if group_by not in df.columns:
            raise KeyError(f"group_by {group_by!r} not in layer")
        series = pd.to_numeric(df[column], errors="coerce")
        summary = {}
        for key, sub in series.groupby(df[group_by]):
            s = sub.dropna()
            summary[str(key)] = {
                "n": int(s.size),
                agg: _num(getattr(s, agg)()) if s.size else None,
            }
        return {"result": summary, "row_count": int(series.notna().sum())}

    def _op_unique(self, df: pd.DataFrame, query: dict) -> dict:
        column = query["column"]
        if column not in df.columns:
            raise KeyError(f"column {column!r} not in layer")
        limit = int(query.get("limit") or 50)
        vals = df[column].dropna().unique().tolist()
        return {
            "result": [str(v) for v in vals[:limit]],
            "row_count": int(len(vals)),
            "n_unique": int(len(vals)),
            "truncated": bool(len(vals) > limit),
        }

    # ------------------------------------------------------------------ errors

    @staticmethod
    def _err(message: str, query: dict) -> dict:
        return {
            "ok": False,
            "error": message,
            "query_description": _describe(query),
        }


def _num(x: Any) -> Any:
    try:
        return round(float(x), 4)
    except (TypeError, ValueError):
        return x


def _describe(query: dict) -> str:
    op = query.get("operation", "?")
    layer = query.get("layer", "?")
    col = query.get("column")
    extra = []
    if col:
        extra.append(f"column={col}")
    if query.get("group_by"):
        extra.append(f"group_by={query['group_by']}")
    if query.get("primary_only"):
        extra.append("primary_only=true")
    if query.get("where") or query.get("filter"):
        extra.append(f"where={query.get('where') or query.get('filter')}")
    tail = ", ".join(extra)
    return f"{op} on {layer}" + (f" ({tail})" if tail else "")
