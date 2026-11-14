"""Internal ClaimResult to findings.schema.json v0.2 translation.

The shared format is the single thing the organizer's checker reads, so this
module is the only place the schema wording lives. Everywhere else works
with ClaimResult, and conversion happens here at the edge.
"""
from __future__ import annotations

import json
import pathlib
from typing import Iterable

from config import HACKATHON_REPO
from core.evidence import ClaimResult
from core.loader import TCGARelease
from core.trace import TraceCollector

_SCHEMA_PATH = HACKATHON_REPO / "format" / "findings.schema.json"


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
    audit: dict = {
        "format_version": "0.2",
        "producer": {"team": team, "product": product, "track": track},
        "data": {
            "dataset": "TCGA-BRCA",
            "releases": [
                {
                    "name": _release_name(release),
                    "files": [
                        {"file": fname, "sha256": sha, "hash_of": "file"}
                        for fname, sha in release.file_checksums().items()
                    ],
                }
            ],
        },
        "question": _summarize_question(report_text, report_path),
        "findings": [
            claim_result_to_finding(r, i) for i, r in enumerate(results, start=1)
        ],
    }
    if trace is not None:
        # Trace is extra context for the reviewer. It is not part of the
        # shared format, so we store it alongside the required fields with a
        # non-colliding key the validator will ignore.
        audit["_trace"] = trace.to_dict()
    return audit


def claim_result_to_finding(result: ClaimResult, index: int) -> dict:
    """Convert one ClaimResult into a schema-compliant finding dict."""
    finding: dict = {
        "id": f"F-{index:03d}",
        "kind": "claim_check",
        "summary": _summary_for(result),
        "severity": result.severity,
        "confidence": result.confidence,
        "evidence": [e.to_dict() for e in result.evidence] or [
            # The schema requires at least one evidence entry on any finding,
            # so an insufficient_evidence verdict with no tool hits still
            # points at the claim itself as the item under review.
            {"kind": "claim", "id": result.claim_text[:60]}
        ],
        "claim_text": result.claim_text,
        "claim_verdict": result.claim_verdict,
        "needs_human_review": bool(result.needs_human_review),
    }
    if result.correct_value:
        finding["correct_value"] = result.correct_value
    if result.limitation:
        finding["limitation"] = result.limitation
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
    return text if len(text) <= limit else text[: limit - 1] + "…"
