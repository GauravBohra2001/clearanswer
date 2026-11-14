"""Full audit pipeline: report in, audit.json dict out.

The orchestrator is the only place that knows about the end-to-end flow,
so swapping a subagent (for example a stronger extractor) means changing
exactly one line here.
"""
from __future__ import annotations

from pathlib import Path

from agents.extractor import ExtractorAgent
from agents.verifier import VerifierAgent
from core.evidence import ClaimResult
from core.guard import post_check, pre_check
from core.loader import TCGARelease
from core.trace import TraceCollector
from output import build_audit_json


class OrchestratorAgent:
    """Coordinates extraction, verification, and audit.json assembly."""

    def __init__(self, team: str = "clearanswer") -> None:
        # One shared TraceCollector keeps every agent's steps in one ordered log.
        self.trace = TraceCollector()
        self.team = team

    def run(self, report_path: str | Path, data_dir: str | Path) -> dict:
        report_path = Path(report_path)
        report_text = report_path.read_text(encoding="utf-8")
        release = TCGARelease(data_dir)

        # Pre-guard: record any flagged phrases in the input report but keep
        # processing. The report is written by researchers, so we only want
        # to surface issues for the reviewer, not refuse the whole audit.
        guard_issues = pre_check(report_text)
        with self.trace.start_step("orchestrator", "guard") as step:
            step.input_data = {"report": str(report_path)}
            step.output_data = {"issues": guard_issues}
            step.reasoning = (
                "Pre-guard pass over the full report text."
                if not guard_issues
                else "Pre-guard flagged phrases; will note them on affected findings."
            )

        extractor = ExtractorAgent(trace_collector=self.trace)
        claims = extractor.run(report_text)

        results: list[ClaimResult] = []
        for claim_text in claims:
            verifier = VerifierAgent(release=release, trace_collector=self.trace)
            result = verifier.run(claim_text)
            # Post-guard: tighten needs_human_review and limitation for weak verdicts.
            post_check(result)
            results.append(result)

        audit = build_audit_json(
            report_text=report_text,
            release=release,
            claim_results=results,
            trace=self.trace,
            team=self.team,
            report_path=str(report_path),
        )
        return audit

    def get_trace(self) -> TraceCollector:
        return self.trace
