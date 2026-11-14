"""Numeric tolerance for claim verification.

Hardcoded thresholds: exact counts must match, percentages +/- 0.5,
approximate claims +/- 1.5 or 5% relative. Applied as a safety net in
verifier._build_result(): if Claude says 'contradicted' but numbers
are within tolerance, upgrade to 'supported' with a note.
"""
from __future__ import annotations

import re
from typing import Optional

_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")
_PERCENT_RE = re.compile(r"([-+]?\d[\d,]*\.?\d*)\s*%")
_APPROX_RE = re.compile(
    r"\b(about|approximately|roughly|around|nearly|close to|~)\b",
    re.IGNORECASE,
)


def extract_first_number(text: str) -> Optional[float]:
    """Pull the first numeric value from a string."""
    m = _NUMBER_RE.search(text)
    if m:
        return float(m.group().replace(",", ""))
    return None


def is_percentage(text: str) -> bool:
    return bool(_PERCENT_RE.search(text))


def is_approximate(text: str) -> bool:
    return bool(_APPROX_RE.search(text))


def within_tolerance(
    claimed: float,
    actual: float,
    is_pct: bool = False,
    is_approx: bool = False,
) -> bool:
    """Check if claimed value is within acceptable tolerance of actual.

    Rules:
    - Exact counts: must match exactly (tolerance 0).
    - Percentages with decimals: +/- 0.5 percentage points.
    - Approximate language: +/- 1.5 percentage points or 5% relative.
    """
    diff = abs(claimed - actual)

    if is_approx:
        threshold = max(1.5, abs(actual) * 0.05)
        return diff <= threshold

    if is_pct:
        return diff <= 0.5

    return diff == 0


def check_tolerance(
    claim_text: str,
    correct_value_str: str,
) -> Optional[str]:
    """Compare numbers in a claim against correct_value.

    Returns a note string if values are within tolerance (meaning
    verdict should be 'supported' not 'contradicted'), or None if
    genuinely different.
    """
    claimed_num = extract_first_number(claim_text)
    actual_num = extract_first_number(correct_value_str)

    if claimed_num is None or actual_num is None:
        return None

    is_pct = is_percentage(claim_text) or is_percentage(correct_value_str)
    is_approx = is_approximate(claim_text)

    if within_tolerance(claimed_num, actual_num, is_pct, is_approx):
        if claimed_num == actual_num:
            return None  # Exact match, should not be contradicted anyway
        return (
            f"Claimed {claimed_num}{'%' if is_pct else ''} vs actual "
            f"{actual_num}{'%' if is_pct else ''} - within "
            f"{'approximate ' if is_approx else ''}tolerance"
            f"{' (+/- 1.5pp / 5%)' if is_approx else ' (+/- 0.5pp)' if is_pct else ''}. "
            f"Treating as supported."
        )
    return None
