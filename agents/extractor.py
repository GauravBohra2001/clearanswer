"""Extracts checkable factual claims from a research report.

An opinion or recommendation cannot be verified against data, so passing
those to the verifier would waste tool calls and produce misleading
insufficient_evidence verdicts. The extractor filters them out at the top
of the pipeline so every downstream claim is one the data can speak to.
"""
from __future__ import annotations

import json
import re

from agents.base import BaseAgent
from core.trace import TraceCollector

_SYSTEM = """You are the claim extractor for a research audit tool.

Input: a short research summary that references the TCGA-BRCA breast cancer dataset.
Output: a JSON array where each entry is ONE checkable factual claim. The
downstream pipeline writes one audit finding per entry, so a sentence that
carries two independent facts must be split into two entries.

A checkable claim is a specific statement the data can confirm or refute:
- counts or percentages ("1,101 primary tumors", "about 62% of primary tumors")
- comparisons ("highest ER-alpha protein responded best")
- data-coverage statements ("535 have survival, mutation, copy number, RNA and protein data")

Do NOT include:
- opinions, recommendations, or future work suggestions ("we recommend...")
- methodology descriptions or framing
- citations or headings
- the sentence "TCGA's breast cancer cohort is one of the most widely used
  public cancer datasets" style opener; it has no number to check.

Rules:
- Each entry must be a span COPIED VERBATIM from the input, keeping the exact
  wording and casing. Do not paraphrase or add words.
- Split a sentence into separate entries ONLY when each half can be verified
  on its own.
- Do NOT split a sentence where one half depends on the other for its subject.

Worked example on a sentence shaped like the practice brief's first body line:
  INPUT: "Of the 1,101 primary tumors in the release, 535 have survival,
  mutation, copy number, RNA and protein data."
  CORRECT OUTPUT (two entries, each a verbatim span):
    - "1,101 primary tumors in the release"
    - "535 have survival, mutation, copy number, RNA and protein data"

Worked example of a sentence that must NOT split:
  INPUT: "Luminal A is the largest RNA subtype, accounting for about 62% of
  primary tumors with an RNA subtype call."
  CORRECT OUTPUT (one entry, the whole sentence):
    - "Luminal A is the largest RNA subtype, accounting for about 62% of
      primary tumors with an RNA subtype call."

Respond with JSON only, no prose. Shape:
  {"claims": ["claim text 1", "claim text 2", ...]}.
"""


class ExtractorAgent(BaseAgent):
    def __init__(self, trace_collector: TraceCollector | None = None) -> None:
        super().__init__(name="extractor", trace_collector=trace_collector)

    def run(self, report_text: str) -> list[str]:
        """Return the list of verbatim sentences that carry checkable claims."""
        with self.trace_collector.start_step(self.name, "extract") as step:
            step.input_data = {"report_length": len(report_text)}
            response = self.call_llm(
                system=_SYSTEM,
                messages=[{"role": "user", "content": report_text}],
                max_tokens=1024,
            )
            raw = _first_text_block(response)
            claims = _parse_claims(raw)
            # Keep only sentences the model actually quoted from the report.
            # Paraphrases would make later evidence pointers unreliable.
            verified = [c for c in claims if _appears_in(report_text, c)]
            step.reasoning = (
                f"Model returned {len(claims)} candidate sentences; "
                f"{len(verified)} matched the report verbatim."
            )
            step.output_data = {"claims": verified}
            return verified


def _first_text_block(response) -> str:
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


def _parse_claims(raw: str) -> list[str]:
    """Pull the claims array out of the model's response.

    The model is instructed to emit {"claims": [...]} but it occasionally
    wraps JSON in prose or code fences, so we extract the first JSON object
    with a 'claims' key rather than trusting the whole response.
    """
    if not raw:
        return []
    match = re.search(r"\{[^{}]*\"claims\"\s*:\s*\[.*?\]\s*\}", raw, re.DOTALL)
    payload = match.group(0) if match else raw
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        # Last-ditch: find the array alone.
        array_match = re.search(r"\[(?:[^\[\]]|\[[^\[\]]*\])*\]", payload, re.DOTALL)
        if not array_match:
            return []
        try:
            arr = json.loads(array_match.group(0))
            return [s.strip() for s in arr if isinstance(s, str) and s.strip()]
        except json.JSONDecodeError:
            return []
    claims = data.get("claims") if isinstance(data, dict) else data
    if not isinstance(claims, list):
        return []
    return [s.strip() for s in claims if isinstance(s, str) and s.strip()]


def _appears_in(report: str, sentence: str) -> bool:
    """True when the model's sentence is really a substring of the report.

    Whitespace is collapsed on both sides because Markdown wrapping often
    inserts line breaks inside what logically reads as one sentence.
    """
    norm_report = re.sub(r"\s+", " ", report).strip().lower()
    norm_claim = re.sub(r"\s+", " ", sentence).strip().lower()
    if not norm_claim:
        return False
    return norm_claim in norm_report
