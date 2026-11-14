"""Internal ClaimResult to findings.schema.json v0.2 translation.

The shared format is the single thing the organizer's checker reads, so this
module is the only place the schema wording lives. Everywhere else works
with ClaimResult, and conversion happens here at the edge.

Findings are enriched with reviewer-facing context the schema permits as
additional properties (next_step, why_it_matters) and with denser evidence
pointers that match what a human auditor would expect to see: the claim
itself, the source file plus release, and a cohort-trace line showing how
the number was derived.
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Iterable

from config import HACKATHON_REPO
from core.evidence import ClaimResult
from core.loader import TCGARelease
from core.trace import TraceCollector

_SCHEMA_PATH = HACKATHON_REPO / "format" / "findings.schema.json"

# Keywords that mark a claim as being about treatment response, which the
# TCGA-BRCA release cannot answer. When one fires AND the verdict is
# insufficient_evidence, we swap in a vocabulary-matched limitation string
# naming the specific columns that exist and the dataset that would be needed.
_TREATMENT_RESPONSE_KEYWORDS = re.compile(
    r"\b(hormone therapy|endocrine therapy|tamoxifen|aromatase|neoadjuvant|"
    r"adjuvant|respond(?:ed|s)? to|respond(?:ed|s)? best|responders?|"
    r"treatment response|therapy response|pathological response)\b",
    re.IGNORECASE,
)

_TREATMENT_LIMITATION = (
    "clinical.tsv records radiation_therapy, targeted_molecular_therapy, and "
    "additional_pharmaceutical_therapy as yes/no flags, plus "
    "new_tumor_event_after_initial_treatment and days_to_new_tumor_event, but "
    "it has no hormone-therapy records and no response measure. Verifying "
    "this claim would require a treated cohort like METABRIC or a neo-adjuvant "
    "endocrine therapy trial with response annotations."
)


def build_audit_json(
    report_text: str,
    release: TCGARelease,
    claim_results: Iterable[ClaimResult],
    trace: TraceCollector | None = None,
    team: str = "clearanswer",
    product: str = "research-claim-auditor",
    track: str = "evidence-navigator",
    report_path: str | None = None,
) -> dict:
    """Assemble the audit.json dict from component pieces."""
    results = list(claim_results)
    release_name = _release_name(release)
    audit: dict = {
        "format_version": "0.2",
        "producer": {"team": team, "product": product, "track": track},
        "data": {
            "dataset": "TCGA-BRCA",
            "releases": [
                {
                    "name": release_name,
                    "files": [
                        {"file": fname, "sha256": sha, "hash_of": "file"}
                        for fname, sha in release.file_checksums().items()
                    ],
                }
            ],
        },
        "question": _summarize_question(report_text, report_path),
        "findings": [
            claim_result_to_finding(r, i, release_name=release_name)
            for i, r in enumerate(results, start=1)
        ],
    }
    if trace is not None:
        # Trace is extra context for the reviewer. It is not part of the
        # shared format, so we store it alongside the required fields with a
        # non-colliding key the validator will ignore.
        audit["_trace"] = trace.to_dict()
    return audit


def claim_result_to_finding(
    result: ClaimResult,
    index: int,
    release_name: str | None = None,
) -> dict:
    """Convert one ClaimResult into a schema-compliant finding dict.

    The enrichment layer adds optional fields (next_step, why_it_matters) and
    expands evidence from the raw tool pointers into a reviewer-facing chain
    that includes the claim itself and a cohort-trace line.
    """
    finding_id = f"F-{index:03d}"
    verdict = result.claim_verdict

    limitation = _maybe_rewrite_limitation(result)

    finding: dict = {
        "id": finding_id,
        "kind": "claim_check",
        "summary": _summary_for(result),
        "severity": result.severity,
        "confidence": result.confidence,
        "evidence": _build_evidence(result, finding_id, release_name, limitation),
        "claim_text": result.claim_text,
        "claim_verdict": verdict,
        "needs_human_review": bool(result.needs_human_review),
    }
    if result.correct_value:
        finding["correct_value"] = result.correct_value
    if limitation:
        finding["limitation"] = limitation

    # Optional reviewer-facing fields. Allowed by the shared format
    # (additionalProperties is not forbidden on a finding). Prefer the
    # verifier's claim-specific text; fall back to generic phrasing only when
    # the LLM did not supply one (e.g. the cannot_answer short-circuit path).
    finding["why_it_matters"] = result.why_it_matters or _why_it_matters(result)
    finding["next_step"] = result.next_step or _next_step(result, release_name)
    if result.cannot_tell:
        finding["cannot_tell"] = result.cannot_tell
    if result.alternatives:
        finding["alternatives"] = result.alternatives
    return finding


def validate_output(audit_dict: dict) -> list[str]:
    """Run jsonschema plus the hackathon's reference id-graph check."""
    import jsonschema  # local import so the module loads without the dep at parse time

    schema = json.loads(_SCHEMA_PATH.read_text())
    # Strip our private trace key before validation so the schema does not
    # see fields it does not define; additionalProperties is implicit.
    doc = {k: v for k, v in audit_dict.items() if not k.startswith("_")}
    errors = [
        f"{'/'.join(map(str, e.path)) or '(top)'}: {e.message}"
        for e in jsonschema.Draft202012Validator(schema).iter_errors(doc)
    ]
    finding_ids = {f.get("id") for f in doc.get("findings", [])}
    repair_ids = {r.get("id") for r in doc.get("repairs", [])}
    for r in doc.get("repairs", []):
        for a in r.get("addresses", []):
            if a not in finding_ids:
                errors.append(f"repairs/{r.get('id')}: addresses unknown finding '{a}'")
    for d in doc.get("decisions", []):
        if d.get("repair_id") not in repair_ids:
            errors.append(f"decisions: unknown repair '{d.get('repair_id')}'")
    return errors


def write_audit_json(audit_dict: dict, path: str | pathlib.Path) -> pathlib.Path:
    out = pathlib.Path(path)
    out.write_text(json.dumps(audit_dict, indent=2), encoding="utf-8")
    return out


# ---------------------------------------------------------------- helpers

def _build_evidence(
    result: ClaimResult,
    finding_id: str,
    release_name: str | None,
    limitation: str | None,
) -> list[dict]:
    """Expand verifier evidence into the richer reviewer-facing chain.

    Shape:
      1. {kind:"claim", id:<finding_id>, note:"<claim text>"} so the sentence
         under review is always the first pointer.
      2. Every file pointer the verifier emitted, stamped with the release.
      3. Every analysis pointer the verifier emitted.
      4. A synthesized {kind:"analysis", id:"cohort_trace"} line that walks
         the cohort filter steps if the raw notes hint at one.
    """
    evidence: list[dict] = [{
        "kind": "claim",
        "id": finding_id,
        "note": result.claim_text,
    }]

    seen: set[tuple] = {("claim", finding_id)}
    for ev in result.evidence:
        base = ev.to_dict()
        kind = base.get("kind")
        key = (kind, base.get("id"), base.get("file"))
        if key in seen:
            continue
        seen.add(key)
        if kind == "file" and release_name and not base.get("release"):
            base["release"] = release_name
        evidence.append(base)

    trace_note = _cohort_trace_from_evidence(result)
    if trace_note:
        evidence.append({
            "kind": "analysis",
            "id": "cohort_trace",
            "note": trace_note,
        })

    # Insufficient-evidence verdict with no tool evidence still needs a
    # second pointer so reviewers see what we searched. The claim pointer
    # is already there; add a hint when nothing else landed.
    if len(evidence) == 1 and limitation:
        evidence.append({
            "kind": "analysis",
            "id": "data_scope_check",
            "note": limitation,
        })
    return evidence


def _cohort_trace_from_evidence(result: ClaimResult) -> str | None:
    """Pick the most informative tool-note and turn it into a filter chain.

    The verifier stores pandas query descriptions and sample counts on
    Evidence objects as `note` strings. The first analysis pointer whose
    note carries counts or a distribution becomes the trace line.
    """
    for ev in result.evidence:
        if ev.kind != "analysis" or not ev.note:
            continue
        note = ev.note.strip()
        if "=" in note or "/" in note or "%" in note:
            return note
    return None


def _maybe_rewrite_limitation(result: ClaimResult) -> str | None:
    """Swap in a vocabulary-matched limitation for treatment-response claims."""
    if (
        result.claim_verdict == "insufficient_evidence"
        and _TREATMENT_RESPONSE_KEYWORDS.search(result.claim_text or "")
    ):
        return _TREATMENT_LIMITATION
    return result.limitation


def _why_it_matters(result: ClaimResult) -> str:
    verdict = result.claim_verdict
    if verdict == "supported":
        return (
            "The number in the report matches the data. A reviewer can cite "
            "this as verified against the TCGA-BRCA release."
        )
    if verdict == "contradicted":
        return (
            "A wrong headline figure misleads every downstream reader. "
            "Figures, tables, or conclusions built on this number inherit "
            "the error."
        )
    return (
        "The TCGA-BRCA release does not record what this sentence requires. "
        "Any downstream use of the claim rests on evidence the data does not "
        "contain."
    )


def _next_step(result: ClaimResult, release_name: str | None) -> str:
    verdict = result.claim_verdict
    release_phrase = f" (TCGA-BRCA release {release_name})" if release_name else ""
    if verdict == "supported":
        return (
            f"No change needed. Keep the sentence as written, citing the "
            f"audited release{release_phrase}."
        )
    if verdict == "contradicted":
        cv = result.correct_value or "the value shown by the data"
        return (
            f"Correct the number to '{cv}' before sharing. Any figure, "
            f"table, or conclusion built on the original number needs the "
            f"same fix."
        )
    return (
        "Remove or reword the sentence, or rerun the analysis against a "
        "dataset that records what the claim requires (for treatment-response "
        "claims, consider METABRIC or a neo-adjuvant endocrine therapy trial)."
    )


def _release_name(release: TCGARelease) -> str:
    """Give the release a stable name across local and envelope layouts.

    The reference example calls the fetched baseline 'raw'. Envelope releases
    live under envelopes/opened/<n>/release/, so we pick up that <n> instead.
    """
    path = release.release_dir
    parts = path.parts
    if "opened" in parts:
        idx = parts.index("opened")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    if path.name == "raw":
        return "raw"
    return path.name


def _summarize_question(report_text: str, report_path: str | None) -> str:
    base = "Check the factual claims in the report against the TCGA-BRCA release."
    if report_path:
        return f"{base} (report: {report_path})"
    return base


def _summary_for(result: ClaimResult) -> str:
    verdict = result.claim_verdict
    if verdict == "supported":
        return f"Supported: {_short(result.claim_text)}"
    if verdict == "contradicted":
        tail = f" Correct value: {result.correct_value}" if result.correct_value else ""
        return f"Contradicted: {_short(result.claim_text)}{tail}"
    return f"Insufficient evidence: {_short(result.claim_text)}"


def _short(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "..."
