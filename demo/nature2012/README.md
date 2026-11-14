# Demo: Nature 2012 TCGA-BRCA paper

Proof that the semantic layer is plug-and-play. Swap one file, restart, and
the same agent audits a different paper with the same guarantees.

## Why this demo exists

ClearAnswer separates three concerns:

- **Agent** (`agents/`) - extracts and verifies claims. Paper-independent.
- **Data model** (`core/data_model.py`) - deterministic pandas queries.
  Dataset-independent in spirit; column names reflect TCGA-BRCA today.
- **Semantic layer** (`core/semantic.py`) - the only place that knows about
  a specific paper or release. It lists columns, operations, and what the
  dataset cannot answer.

To audit a new paper, you only touch the semantic layer. This demo ships a
drop-in version of that file scoped to the 2012 Nature paper, so you can
see the swap in action without changing anything else.

## The paper

**"Comprehensive molecular portraits of human breast tumours"**, The Cancer
Genome Atlas Network, *Nature* 490, 61-70 (2012).
DOI: [10.1038/nature11412](https://doi.org/10.1038/nature11412).

The paper analyzed a 2011 freeze of TCGA-BRCA, before the cohort grew to
its current size. Our tool runs against the current GDC release pulled via
`data/tcga-brca/fetch.py`, so the headline numbers in the paper are
expected to differ from what the data shows today. That is exactly what an
auditor is for: the tool will mark those differences as `contradicted`
(when they exceed tolerance) with the correct current value, or
`supported` when the paper's number still holds.

## How to switch to this demo

From the repo root, with the Flask server stopped:

```bash
cp demo/nature2012/semantic_nature2012.py core/semantic.py
PORT=5050 python app.py
```

Then upload the Nature paper (as PDF) in the browser, or use
[sample_claims.md](sample_claims.md) for a quick inline test.

To switch back:

```bash
git checkout core/semantic.py
```

## What changed vs. the default semantic layer

Two things, both intentional:

1. **Docstring and dataset description** now reference the Nature paper
   and explain why its numbers differ from today's release.
2. **`cannot_answer` list drops "hormone therapy" and "endocrine therapy".**
   The Nature paper discusses treatment-response patterns. If a reviewer
   wants the tool to check those claims, short-circuiting them up front
   would be the wrong default - the reviewer would never see what the
   data actually contains. With the pre-check removed, the agent queries
   the data, finds no response column, and returns `insufficient_evidence`
   with evidence pointers at the files it looked in. Same verdict, reached
   by inspection rather than by table lookup.

Everything else - the agent prompt, the tool calls, the tolerance safety
net, the impact analysis, the exports - stays as it was.

## What stays the same

- Full-sentence claim extraction (DisleveK rule).
- Deterministic pandas queries in `core/data_model.py`.
- Tolerance check: contradicted claims within +/-0.5pp (or +/-1.5pp on
  "about X") are upgraded to supported.
- `why_it_matters`, `next_step`, `cannot_tell` impact fields.
- `audit.json` validates under `format/validate.py`.
- Standalone HTML report export.
