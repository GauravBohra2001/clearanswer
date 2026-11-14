"""Guardrails - regex-based, fast, explainable.

Runs before verification (pre_check on the raw claim text) and after
verification (post_check on the ClaimResult) to enforce the hackathon's
out-of-scope rule: no diagnosis, no treatment recommendation, no risk score,
no re-identification, no clinical claim.

The patterns are kept explicit and categorized so a reviewer can see exactly
why something was flagged. These do NOT call an LLM.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.evidence import ClaimResult


_PATTERNS: dict[str, list[re.Pattern]] = {
    "clinical_recommendation": [
        re.compile(r"\b(?:we\s+)?recommend(?:ed|ing|s)?\s+(?:prescrib|treat|administer|starting|using|giving)", re.I),
        re.compile(r"\b(?:prescrib|administer)(?:e|ed|ing|es)\b", re.I),
        re.compile(r"\bshould\s+(?:be\s+)?(?:treat(?:ed)?|prescribed|administered|given|started\s+on)\b", re.I),
        re.compile(r"\b(?:first-line|second-line)\s+(?:treatment|therapy|option)\b", re.I),
        re.compile(r"\bstandard\s+of\s+care\b", re.I),
    ],
    "diagnosis": [
        re.compile(r"\b(?:patient|case)\s+(?:is\s+)?diagnosed\s+with\b", re.I),
        re.compile(r"\bdiagnosis\s+of\b", re.I),
        re.compile(r"\bthis\s+patient\s+has\b", re.I),
    ],
    "risk_score_or_prognosis": [
        re.compile(r"\b(?:will|likely to)\s+(?:die|survive|relapse|recur|respond)\b", re.I),
        re.compile(r"\b(?:individual|personal|patient)\s+risk\s+(?:score|estimate|prediction)\b", re.I),
        re.compile(r"\bprognosis\s+(?:is|of)\s+(?:poor|good|excellent|unfavou?rable)\b", re.I),
    ],
    "reidentification": [
        re.compile(r"\b(?:re-?identify|deanonymi[sz]e|match\s+to\s+(?:named|real)\s+(?:patient|individual))\b", re.I),
        re.compile(r"\b(?:lookup|look\s+up)\s+(?:the\s+)?patient[’'`]?s?\s+(?:name|address|contact)\b", re.I),
    ],
    "pii_or_contact": [
        # US phone
        re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        # SSN
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        # Email
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ],
    "regulatory_or_production_claim": [
        re.compile(r"\b(?:FDA[- ]approved|CE[- ]marked|clinically\s+validated|production[- ]ready)\b", re.I),
        re.compile(r"\bHIPAA[- ]compliant\b", re.I),
    ],
}


def pre_check(text: str) -> list[str]:
    """Return a list of issue strings found in `text`.

    Each issue is formatted "<category>: '<matched snippet>'" so a reviewer can
    see what fired. An empty list means the text looks safe for processing.
    """
    if not text or not isinstance(text, str):
        return []
    issues: list[str] = []
    for category, patterns in _PATTERNS.items():
        for pat in patterns:
            match = pat.search(text)
            if match:
                snippet = match.group(0)
                issues.append(f"{category}: {snippet!r}")
                break  # one hit per category is enough
    return issues


def post_check(result: "ClaimResult") -> "ClaimResult":
    """Attach human-review flags and limitations when the verdict is weak.

    Mutates `result` in place and returns it for chaining.
    """
    notes: list[str] = []
    if result.confidence == "low":
        result.needs_human_review = True
        notes.append("low confidence")
    if result.claim_verdict in ("supported", "contradicted") and len(result.evidence) < 2:
        notes.append("thin evidence (fewer than 2 pointers)")
        result.needs_human_review = True
    if result.claim_verdict == "insufficient_evidence" and not result.limitation:
        notes.append("missing limitation description")
    if notes:
        prefix = "Auto-guard: " + "; ".join(notes)
        result.limitation = prefix if not result.limitation else f"{result.limitation} | {prefix}"
    return result
