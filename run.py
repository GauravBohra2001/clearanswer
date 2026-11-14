"""CLI entry point for the Research Claim Auditor.

Usage:
    python run.py <data_dir> <report.md> [--output audit.json] [--verbose]

The judge will point this at an envelope-unsealed release directory and the
report from the envelope. This is the only script the judge needs to run.
"""
from __future__ import annotations

import argparse
import sys

from agents.orchestrator import OrchestratorAgent
from output import validate_output, write_audit_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the factual claims in a research report against a TCGA-BRCA release.")
    parser.add_argument("data_dir", help="Path to a TCGA-BRCA release directory (for example oncosys-hackathon-challenge/data/tcga-brca/raw/ or envelopes/opened/E07/release/).")
    parser.add_argument("report", help="Path to the research report Markdown file.")
    parser.add_argument("--output", default="audit.json", help="Path to write the audit JSON (default: audit.json).")
    parser.add_argument("--verbose", action="store_true", help="Also print the full agent trace in Markdown.")
    parser.add_argument("--team", default="clearanswer", help="Team name recorded in audit.json producer.")
    args = parser.parse_args()

    orchestrator = OrchestratorAgent(team=args.team)
    try:
        audit = orchestrator.run(report_path=args.report, data_dir=args.data_dir)
    except Exception as e:  # noqa: BLE001 — surfaced to the judge's terminal
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    out_path = write_audit_json(audit, args.output)
    findings = audit.get("findings", [])
    print(f"Extracted {len(findings)} claims from {args.report}.")
    for f in findings:
        label = f["claim_verdict"].upper()
        extra = ""
        if f["claim_verdict"] == "contradicted" and f.get("correct_value"):
            extra = f" (data shows {f['correct_value']})"
        print(f"  [{f['id']}] {label}{extra}: {f['claim_text']}")

    errors = validate_output(audit)
    if errors:
        print("\nvalidation FAILED:")
        for err in errors:
            print(f"  - {err}")
    else:
        print("\nvalidation: OK (matches findings.schema.json v0.2)")
    print(f"Audit written to: {out_path}")

    if args.verbose:
        print("\n----- TRACE -----")
        print(orchestrator.get_trace().to_markdown())

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
