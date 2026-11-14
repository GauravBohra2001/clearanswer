"""Verifier: the plan/query/execute/interpret/reflect loop.

The agent decides HOW to check a claim. The tools decide WHAT the number is.
Keeping the pandas work on the tool side is deliberate: it means a verdict is
always backed by a deterministic computation that a judge can rerun, not by
the model's opinion about what the number ought to be.

Each verification is one Anthropic tool_use loop. The agent is forced to
emit a final JSON verdict through a dedicated finalize tool once it has
enough evidence, which keeps the verdict shape stable even when the model
is otherwise chatty.
"""
from __future__ import annotations

import json
import re
from typing import Any

from agents.base import BaseAgent
from config import MAX_RETRIES
from core.evidence import ClaimResult, Evidence, contradicted, insufficient, supported
from core.loader import LAYER_FILES, TCGARelease
from core.semantic import check_cannot_answer, get_schema_summary_for_prompt
from core.trace import TraceCollector
from tools.data_tool import DataTool
from tools.manifest_tool import ManifestTool
from tools.schema_tool import SchemaTool

_MAX_STEPS = 10  # upper bound on tool calls per claim so a stuck agent cannot hang the run

_SYSTEM = """You are the verifier in a research claim auditor for the TCGA-BRCA dataset.

You check ONE sentence at a time against real data. The sentence is the full
claim as written in the report. Reason carefully, then use tools. Do not
guess numbers from memory; every number in your verdict must come from a tool
result.

Loop:
1. PLAN what each checkable number or comparison in the sentence asserts and
   which data layer it lives in.
2. QUERY the data using the tools below.
3. INTERPRET each tool result against the matching sub-claim.
4. REFLECT: did you filter correctly (primary tumors only when relevant), did
   you use the right column, is the sentence talking about a different
   denominator?
5. When you are confident, call the finalize tool EXACTLY ONCE with your verdict.

COMPOUND SENTENCES (worst-part-wins rule):
A sentence can carry several numbers ("Of the 1,101 primary tumors in the
release, 535 have survival, mutation, copy number, RNA and protein data").
Check EVERY number in the sentence. The sentence gets ONE verdict:
- supported: every sub-claim matched the data within reasonable rounding.
- contradicted: AT LEAST ONE sub-claim disagrees. correct_value must list
  what the data shows for the wrong sub-claim(s). If more than one is wrong,
  list all of them, separated by '; '.

Verdict rules:
- supported: every checkable part of the sentence agrees with the data.
- contradicted: any part disagrees. You MUST provide correct_value. For
  distributional claims ("largest subtype at 62%") include the correct share
  AND the full distribution in correct_value, e.g.
  '49.9% (421 of 844); full distribution: LumA 49.9%, LumB 22.7%, Basal 16.7%,
   Her2 7.9%, Normal 2.7%'.
- insufficient_evidence: the data cannot speak to the sentence. In the
  limitation field name the specific columns you searched and the dataset or
  measure that would be needed, e.g. 'clinical.tsv records
  radiation_therapy, targeted_molecular_therapy, and
  additional_pharmaceutical_therapy as yes/no flags but has no hormone
  therapy records and no response measure; would require a treated cohort
  like METABRIC or a neo-adjuvant endocrine therapy trial.'

Keep reasoning concise. Prefer the manifest for cohort counts, schema_info to
discover columns, and data_query for the actual numbers.

Dataset Schema (TCGA-BRCA):

{schema_summary}

IMPORTANT RULES:
- ONLY use columns listed above. If a column is not listed, it does not exist.
- Check the "DOES NOT HAVE" lists FIRST. If the sentence requires data in a
  DOES NOT HAVE list, call finalize_verdict('insufficient_evidence') right away
  with a limitation that names the missing field.
- Check "CANNOT ANSWER" FIRST. If the sentence topic matches, call
  finalize_verdict('insufficient_evidence') with the reason from the schema.
- Use the "LIMITATION" field on columns to inform your limitation text.
- When a sentence mentions treatment response, hormone therapy, drug
  efficacy, or causal relationships, the answer is ALWAYS insufficient_evidence.

IMPACT ANALYSIS (fill these in finalize_verdict):
- why_it_matters: one sentence on why THIS specific finding matters. Refer to
  the actual numbers, columns, or distributions you found. Never generic.
- next_step: one concrete action. Name the table/figure/section to fix, or the
  specific column to cite. Never "no change needed" alone.
- cannot_tell: what this audit cannot tell the reviewer about this specific
  claim (optional). Name the specific gap - e.g. a column that exists but
  was not used, or a newer release that might differ.
""".replace("{schema_summary}", get_schema_summary_for_prompt())


def _finalize_tool_schema() -> dict:
    return {
        "name": "finalize_verdict",
        "description": (
            "Record the final verdict for the claim. Call this exactly once "
            "when you have enough evidence. Required fields depend on the verdict."
        ),
        "input_schema": {
            "type": "object",
            "required": ["verdict", "confidence", "severity", "reasoning"],
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["supported", "contradicted", "insufficient_evidence"],
                },
                "correct_value": {
                    "type": "string",
                    "description": (
                        "What the data actually shows. REQUIRED when verdict "
                        "is 'contradicted' (e.g. '49.9% (421 of 844)')."
                    ),
                },
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "severity": {
                    "type": "string",
                    "enum": ["high", "medium", "low", "none"],
                    "description": (
                        "How badly a wrong claim would mislead a reviewer. "
                        "Use 'high' for a contradicted headline statistic, "
                        "'none' for a supported claim."
                    ),
                },
                "reasoning": {
                    "type": "string",
                    "description": "One or two sentences on how the data supports the verdict.",
                },
                "limitation": {
                    "type": "string",
                    "description": "Caveats a reviewer should know about (optional).",
                },
                "evidence_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Source files that back the verdict (e.g. 'clinical.tsv').",
                },
                "why_it_matters": {
                    "type": "string",
                    "description": (
                        "One sentence explaining why THIS specific finding matters "
                        "for a reviewer. Be specific to the claim's actual data - "
                        "e.g. 'A 12-point overstatement of Luminal A prevalence "
                        "skews any subtype-stratified survival analysis built on it.' "
                        "Never use generic language like 'the number matches'."
                    ),
                },
                "next_step": {
                    "type": "string",
                    "description": (
                        "One concrete action for the reviewer. Be specific - "
                        "e.g. 'Correct 62% to 49.9% in Table 2 and re-derive the "
                        "survival curves in Figure 4 that used this denominator.' "
                        "Never say just 'no change needed'."
                    ),
                },
                "cannot_tell": {
                    "type": "string",
                    "description": (
                        "What this audit CANNOT tell the reviewer about this claim "
                        "(optional). E.g. 'This check used the frozen TCGA-BRCA "
                        "release; a newer GDC release may have different counts.' "
                        "Omit if there is nothing beyond the limitation."
                    ),
                },
            },
        },
    }


class VerifierAgent(BaseAgent):
    def __init__(
        self,
        release: TCGARelease,
        trace_collector: TraceCollector | None = None,
    ) -> None:
        super().__init__(name="verifier", trace_collector=trace_collector)
        self.release = release
        # One tool instance per release so every call runs against the same data.
        self.data_tool = DataTool(release)
        self.schema_tool = SchemaTool(release)
        self.manifest_tool = ManifestTool(release)
        self._tools_by_name = {
            self.data_tool.name: self.data_tool,
            self.schema_tool.name: self.schema_tool,
            self.manifest_tool.name: self.manifest_tool,
        }
        self._tool_schemas = [
            self._tool_schema(self.data_tool, self.data_tool.schema()),
            self._tool_schema(self.schema_tool, _schema_tool_schema()),
            self._tool_schema(self.manifest_tool, _manifest_tool_schema()),
            _finalize_tool_schema(),
        ]

    # ------------------------------------------------------------------- run

    def run(self, claim_text: str) -> ClaimResult:
        # Semantic-layer pre-check: if the claim's topic is in cannot_answer
        # (hormone therapy, treatment response, drug efficacy, causal claims)
        # we short-circuit instead of burning tool calls. This is what turns
        # a 24-step fumble into a single decisive step.
        blocked = check_cannot_answer(claim_text)
        if blocked:
            with self.trace_collector.start_step(self.name, "plan") as step:
                step.input_data = {"claim": claim_text}
                step.reasoning = (
                    f"Semantic pre-check: claim matches cannot_answer topic "
                    f"'{blocked['topic']}'. Skipping tool calls."
                )
                step.output_data = {"short_circuit": True, "topic": blocked["topic"]}
            with self.trace_collector.start_step(self.name, "interpret") as step:
                step.input_data = {"verdict": "insufficient_evidence"}
                step.output_data = {
                    "verdict": "insufficient_evidence",
                    "confidence": "high",
                }
                step.reasoning = blocked["reason"]
            return insufficient(
                claim_text=claim_text,
                reason=blocked["reason"],
                confidence="high",
                evidence=self._pre_check_evidence(blocked),
            )

        messages: list[dict] = [{"role": "user", "content": _user_prompt(claim_text)}]
        tool_history: list[dict] = []
        final_input: dict | None = None
        steps = 0

        while steps < _MAX_STEPS:
            steps += 1
            response = self.call_llm(
                system=_SYSTEM,
                messages=messages,
                tools=self._tool_schemas,
                max_tokens=2048,
            )
            assistant_content = [_block_to_dict(b) for b in response.content]
            messages.append({"role": "assistant", "content": assistant_content})

            reasoning_text = _collect_text(response.content)
            tool_use_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]

            # The model's thinking for this turn is one PLAN entry, not a
            # per-tool duplication. When the model decides to fire several
            # tools in the same turn, we record its reasoning once.
            if reasoning_text:
                with self.trace_collector.start_step(self.name, "plan") as step:
                    step.input_data = {"claim": claim_text} if steps == 1 else None
                    step.reasoning = reasoning_text

            if not tool_use_blocks:
                # Model stopped without finalizing. Break so the fallback runs.
                with self.trace_collector.start_step(self.name, "reflect") as step:
                    step.reasoning = reasoning_text or "Model returned no tool calls."
                    step.output_data = {"stop_reason": getattr(response, "stop_reason", None)}
                break

            tool_results_block: list[dict] = []
            finalized = False
            for tu in tool_use_blocks:
                name = tu.name
                tool_input = tu.input or {}
                if name == "finalize_verdict":
                    final_input = tool_input
                    with self.trace_collector.start_step(self.name, "interpret") as step:
                        step.input_data = {
                            "verdict": tool_input.get("verdict"),
                            "correct_value": tool_input.get("correct_value"),
                        }
                        step.output_data = _verdict_summary(tool_input)
                        step.reasoning = tool_input.get("reasoning") or ""
                    tool_results_block.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": "Verdict recorded.",
                    })
                    finalized = True
                    continue

                tool = self._tools_by_name.get(name)
                stage = "query" if name == self.schema_tool.name else "execute"
                # No reasoning attached here on purpose: the preceding PLAN
                # entry already carries the model's intent for this turn.
                # Each tool step records only what makes it unique (its tool
                # call and the result), so the trace reads as a clean audit
                # log instead of repeating the same reasoning N times.
                with self.trace_collector.start_step(self.name, stage) as step:
                    step.input_data = {"tool": name, "args": tool_input}
                    result = tool.execute(tool_input) if tool else {
                        "ok": False, "error": f"unknown tool {name!r}",
                    }
                    step.output_data = _trim_for_trace(result)
                    step.tool_calls = [{"name": name, "input": tool_input}]
                tool_history.append({"name": name, "input": tool_input, "result": result})
                tool_results_block.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(_trim_for_trace(result)),
                })

            messages.append({"role": "user", "content": tool_results_block})
            if finalized:
                break

        if final_input is None:
            # The model exhausted its budget without finalizing. Return a
            # defensive insufficient_evidence verdict rather than crashing,
            # but keep pointers to whatever files the verifier DID check
            # before it ran out of steps. A reviewer needs to see what we
            # looked at, not just a bare "budget_exhausted" marker.
            partial_evidence = self._build_evidence(tool_history, declared_files=[])
            partial_evidence.append(
                Evidence(
                    kind="analysis",
                    id="budget_exhausted",
                    note=(
                        f"Verifier gave up after {_MAX_STEPS} tool calls without "
                        f"emitting finalize_verdict. Evidence above lists the "
                        f"files and queries it did run."
                    ),
                )
            )
            fallback = insufficient(
                claim_text=claim_text,
                reason="Verifier exhausted its reasoning budget without reaching a verdict.",
                confidence="low",
                evidence=partial_evidence,
            )
            fallback.reasoning = "Verifier did not emit finalize_verdict within the step budget."
            return fallback

        return self._build_result(claim_text, final_input, tool_history)

    def _pre_check_evidence(self, blocked: dict) -> list[Evidence]:
        """Evidence for a cannot_answer short-circuit.

        The pre-check didn't run any tools, but a reviewer still needs to see
        what the semantic layer looked at and found lacking. We point at the
        clinical and protein files (the two that most topics would need) plus
        a schema-layer analysis pointer naming the blocked topic.
        """
        topic = blocked.get("topic", "unknown")
        reason = blocked.get("reason", "")
        evidence = [
            Evidence(
                kind="analysis",
                id="semantic_pre_check",
                note=f"Topic '{topic}' is in cannot_answer. Reason: {reason}",
            ),
            Evidence(
                kind="file",
                id=LAYER_FILES["clinical"],
                note="Schema inspected; no matching column for the claimed topic.",
            ),
        ]
        # Protein-specific topics also benefit from naming the RPPA file,
        # even though we did not scan its rows.
        if any(k in topic.lower() for k in ("protein", "er-alpha", "er alpha", "hormone", "response")):
            evidence.append(Evidence(
                kind="file",
                id=LAYER_FILES["protein"],
                note="RPPA protein file available but carries no treatment-response data.",
            ))
        return evidence

    # ----------------------------------------------- result assembly helpers

    def _build_result(
        self,
        claim_text: str,
        final_input: dict,
        tool_history: list[dict],
    ) -> ClaimResult:
        verdict = final_input.get("verdict", "insufficient_evidence")
        confidence = final_input.get("confidence", "medium")
        severity = final_input.get("severity", "none")
        reasoning = final_input.get("reasoning", "")
        limitation = final_input.get("limitation")
        correct_value = final_input.get("correct_value") or ""
        files = list(final_input.get("evidence_files") or [])
        why_it_matters = final_input.get("why_it_matters")
        next_step = final_input.get("next_step")
        cannot_tell = final_input.get("cannot_tell")

        evidence = self._build_evidence(tool_history, files)

        if verdict == "contradicted":
            if not correct_value:
                # Contract would otherwise raise; keep an informative message.
                correct_value = _infer_correct_value(tool_history) or "not stated by verifier"
            result = contradicted(
                claim_text=claim_text,
                correct_value=correct_value,
                evidence=evidence,
                reasoning=reasoning,
                confidence=confidence,
                severity=severity or "high",
                limitation=limitation,
            )
        elif verdict == "supported":
            if not evidence:
                # output.py always prepends a claim pointer; use a distinct
                # analysis marker here so the two do not duplicate on screen.
                evidence = [Evidence(kind="analysis", id="model_asserted_match")]
            result = supported(
                claim_text=claim_text,
                evidence=evidence,
                reasoning=reasoning,
                confidence=confidence,
                severity=severity or "none",
                limitation=limitation,
            )
        else:
            result = insufficient(
                claim_text=claim_text,
                reason=limitation or reasoning or "The data does not record what the claim requires.",
                confidence=confidence,
                severity=severity or "none",
                evidence=evidence,
            )

        result.why_it_matters = why_it_matters
        result.next_step = next_step
        result.cannot_tell = cannot_tell
        return result

    def _build_evidence(
        self,
        tool_history: list[dict],
        declared_files: list[str],
    ) -> list[Evidence]:
        evidence: list[Evidence] = []
        seen: set[tuple[str, str]] = set()

        # Every successful tool call that cites a source file becomes a file
        # evidence pointer, so a reviewer can retrace exactly what was queried.
        for entry in tool_history:
            result = entry.get("result") or {}
            if not result.get("ok"):
                continue
            source = result.get("source_file")
            if source and (ident := ("file", source)) not in seen:
                evidence.append(Evidence(
                    kind="file",
                    id=source,
                    note=result.get("query_description"),
                ))
                seen.add(ident)

            # Also name an analysis pointer per successful data_query so the
            # reviewer can see which computation produced the verdict.
            if entry.get("name") == DataTool.name:
                desc = result.get("query_description") or entry.get("input", {}).get("operation", "query")
                aid = f"A:{desc}"[:80]
                if ("analysis", aid) not in seen:
                    evidence.append(Evidence(
                        kind="analysis",
                        id=aid,
                        note=_short_result(result),
                    ))
                    seen.add(("analysis", aid))

        # Any files the model explicitly cited but no successful tool touched.
        for fname in declared_files:
            if ("file", fname) not in seen:
                evidence.append(Evidence(kind="file", id=fname))
                seen.add(("file", fname))

        return evidence

    # ----------------------------------------------- Anthropic tool schemas

    @staticmethod
    def _tool_schema(tool, input_schema: dict) -> dict:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": input_schema,
        }


def _schema_tool_schema() -> dict:
    return {
        "type": "object",
        "required": ["action"],
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_layers", "columns", "dtypes", "sample_values",
                    "unique_values", "describe_column", "search_columns",
                ],
            },
            "layer": {"type": "string"},
            "column": {"type": "string"},
            "query": {"type": "string"},
            "n": {"type": "integer"},
            "limit": {"type": "integer"},
        },
    }


def _manifest_tool_schema() -> dict:
    return {
        "type": "object",
        "required": ["action"],
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "count_samples", "count_with_layers", "sample_info",
                    "layer_availability", "has_all_layers",
                ],
            },
            "sample_type": {"type": "string"},
            "sample_id": {"type": "string"},
            "layers": {"type": "array", "items": {"type": "string"}},
        },
    }


# ---------------------------------------------------------- utility helpers

def _user_prompt(claim_text: str) -> str:
    return (
        "Verify this claim against the TCGA-BRCA release.\n\n"
        f"Claim: {claim_text}\n\n"
        "Plan what to check, call the tools you need, then call finalize_verdict."
    )


def _block_to_dict(block) -> dict:
    """Serialize a response content block for round-tripping to the API."""
    btype = getattr(block, "type", None)
    if btype == "text":
        return {"type": "text", "text": block.text}
    if btype == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    # Fallback keeps forward compatibility if new block types appear.
    return {"type": btype or "unknown"}


_EMOJI_RE = re.compile(
    "[☀-➿\U0001F300-\U0001FAFF✅❌✔✖⚠✨✎]"
)


def _collect_text(blocks) -> str:
    """Join model text blocks, stripping any emoji so traces stay plain ASCII.

    The model sometimes decorates reasoning with checkmarks or warning signs
    which clutter the audit trace. Reviewers read the trace as prose, so we
    scrub emoji at collection time rather than filtering at render time.
    """
    chunks = [b.text for b in blocks if getattr(b, "type", None) == "text"]
    joined = " ".join(c.strip() for c in chunks if c and c.strip())
    return _EMOJI_RE.sub("", joined).strip()


def _trim_for_trace(result: Any, limit: int = 40) -> Any:
    """Cap long result lists so the trace stays readable."""
    if isinstance(result, dict):
        return {k: _trim_for_trace(v, limit) for k, v in result.items()}
    if isinstance(result, list) and len(result) > limit:
        return result[:limit] + [f"...({len(result) - limit} more)"]
    return result


def _short_result(result: dict) -> str:
    """One-line summary of a data_query result for evidence notes."""
    r = result.get("result")
    if isinstance(r, dict):
        preview = ", ".join(f"{k}={v}" for k, v in list(r.items())[:5])
        return preview
    if isinstance(r, (int, float, str)):
        return str(r)
    return str(result.get("row_count", ""))


def _verdict_summary(final_input: dict) -> dict:
    """Compact, distinct payload for the INTERPRET trace step."""
    summary = {
        "verdict": final_input.get("verdict"),
        "confidence": final_input.get("confidence"),
    }
    if final_input.get("correct_value"):
        summary["correct_value"] = final_input["correct_value"]
    return summary


def _infer_correct_value(tool_history: list[dict]) -> str:
    """Last-resort correct_value for a contradicted claim.

    When the model forgets to fill correct_value, pull a reasonable summary
    from the most recent successful data_query so the schema's requirement
    still holds without fabricating numbers.
    """
    for entry in reversed(tool_history):
        if entry.get("name") != DataTool.name:
            continue
        result = entry.get("result") or {}
        if not result.get("ok"):
            continue
        return _short_result(result)
    return ""


# MAX_RETRIES is exposed as the recommended refinement budget; the step budget
# above enforces the hard ceiling on tool calls per claim.
__all__ = ["VerifierAgent", "MAX_RETRIES"]
