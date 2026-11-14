"""Evidence contract for claim verdicts.

Think of ClaimResult as a compile-time check: a verdict cannot be constructed
without the proof the shared format requires. If a verdict says "contradicted",
__post_init__ demands a correct_value; if it says "supported" or
"contradicted", it demands at least one Evidence pointer. The only verdict
that doesn't need evidence is "insufficient_evidence" - because the whole
point is that the data can't support an answer.

Use the module-level constructors (supported, contradicted, insufficient)
rather than ClaimResult(...) directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

EVIDENCE_KINDS = (
    "sample", "patient", "gene", "protein", "slide",
    "file", "release", "analysis", "claim", "row",
)
VERDICTS = ("supported", "contradicted", "insufficient_evidence")
CONFIDENCES = ("high", "medium", "low")
SEVERITIES = ("high", "medium", "low", "none")


@dataclass
class Evidence:
    kind: str
    id: str
    release: Optional[str] = None
    file: Optional[str] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in EVIDENCE_KINDS:
            raise ValueError(
                f"Evidence.kind must be one of {EVIDENCE_KINDS}, got {self.kind!r}"
            )
        if not self.id:
            raise ValueError("Evidence.id is required")

    def to_dict(self) -> dict:
        d = {"kind": self.kind, "id": self.id}
        if self.release:
            d["release"] = self.release
        if self.file:
            d["file"] = self.file
        if self.note:
            d["note"] = self.note
        return d


@dataclass
class ClaimResult:
    claim_text: str
    claim_verdict: str
    correct_value: Optional[str] = None
    confidence: str = "medium"
    severity: str = "none"
    evidence: list[Evidence] = field(default_factory=list)
    limitation: Optional[str] = None
    needs_human_review: bool = False
    reasoning: str = ""
    trace: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.claim_verdict not in VERDICTS:
            raise ValueError(
                f"claim_verdict must be one of {VERDICTS}, got {self.claim_verdict!r}"
            )
        if self.confidence not in CONFIDENCES:
            raise ValueError(
                f"confidence must be one of {CONFIDENCES}, got {self.confidence!r}"
            )
        if self.severity not in SEVERITIES:
            raise ValueError(
                f"severity must be one of {SEVERITIES}, got {self.severity!r}"
            )
        if self.claim_verdict == "contradicted" and not self.correct_value:
            raise ValueError(
                "A contradicted claim requires a non-empty correct_value "
                "(e.g. '49.9% (421 of 844)')."
            )
        if self.claim_verdict in ("supported", "contradicted") and not self.evidence:
            raise ValueError(
                f"A {self.claim_verdict!r} claim requires at least one evidence entry."
            )

    def to_dict(self) -> dict:
        d: dict = {
            "claim_text": self.claim_text,
            "claim_verdict": self.claim_verdict,
            "confidence": self.confidence,
            "severity": self.severity,
            "evidence": [e.to_dict() for e in self.evidence],
            "needs_human_review": self.needs_human_review,
            "reasoning": self.reasoning,
        }
        if self.correct_value:
            d["correct_value"] = self.correct_value
        if self.limitation:
            d["limitation"] = self.limitation
        return d


def supported(
    claim_text: str,
    evidence: list[Evidence],
    reasoning: str = "",
    confidence: str = "high",
    severity: str = "none",
    limitation: Optional[str] = None,
    needs_human_review: bool = False,
) -> ClaimResult:
    return ClaimResult(
        claim_text=claim_text,
        claim_verdict="supported",
        evidence=list(evidence),
        confidence=confidence,
        severity=severity,
        reasoning=reasoning,
        limitation=limitation,
        needs_human_review=needs_human_review,
    )


def contradicted(
    claim_text: str,
    correct_value: str,
    evidence: list[Evidence],
    reasoning: str = "",
    confidence: str = "high",
    severity: str = "high",
    limitation: Optional[str] = None,
    needs_human_review: bool = False,
) -> ClaimResult:
    return ClaimResult(
        claim_text=claim_text,
        claim_verdict="contradicted",
        correct_value=correct_value,
        evidence=list(evidence),
        confidence=confidence,
        severity=severity,
        reasoning=reasoning,
        limitation=limitation,
        needs_human_review=needs_human_review,
    )


def insufficient(
    claim_text: str,
    reason: str,
    confidence: str = "medium",
    severity: str = "none",
    evidence: Optional[list[Evidence]] = None,
    needs_human_review: bool = True,
) -> ClaimResult:
    """Insufficient-evidence verdict. `reason` is what data would be needed.

    Evidence is optional here (unlike supported/contradicted). When provided,
    it typically points at the columns searched or files consulted.
    """
    return ClaimResult(
        claim_text=claim_text,
        claim_verdict="insufficient_evidence",
        evidence=list(evidence or []),
        confidence=confidence,
        severity=severity,
        reasoning=reason,
        limitation=reason,
        needs_human_review=needs_human_review,
    )
