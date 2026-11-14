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
from typing import Any

from agents.base import BaseAgent
from config import MAX_RETRIES
from core.evidence import ClaimResult, Evidence, contradicted, insufficient, supported
from core.loader import TCGARelease
from core.trace import TraceCollector
from tools.data_tool import DataTool
from tools.manifest_tool import ManifestTool
from tools.schema_tool import SchemaTool

_MAX_STEPS = 10  # upper bound on tool calls per claim so a stuck agent cannot hang the run

_SYSTEM = """You are the verifier in a research claim auditor for the TCGA-BRCA dataset.

You check ONE claim at a time against real data. Reason carefully, then use tools.
Do not guess numbers from memory; every number in your verdict must come from a tool result.

Loop:
1. PLAN what the claim asserts and which data layer it lives in.
2. QUERY the data using the tools below.
3. INTERPRET the tool result against the claim.
4. REFLECT: did you filter correctly (primary tumors only when relevant), did you
   use the right column, is the claim talking about a different denominator?
5. When you are confident, call the finalize tool EXACTLY ONCE with your verdict.

Verdict rules:
- supported: the data confirms the claim within reasonable rounding.
- contradicted: the data disagrees. You MUST provide correct_value (what the
  data actually shows, e.g. '49.9% (421 of 844)').
- insufficient_evidence: the data cannot speak to the claim. Explain what
  would be needed. Use this for claims about treatment response, prognosis,
  or anything the TCGA-BRCA release does not record.

Keep reasoning concise. Prefer the manifest for cohort counts, schema_info to
discover columns, and data_query for the actual numbers.
"""


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
        messages: list[dict] = [{"role": "user", "content": _user_prompt(claim_text)}]
        tool_history: list[dict] = []
        final_input: dict | None = None
        steps = 0

        with self.trace_collector.start_step(self.name, "plan") as step:
            step.input_data = {"claim": claim_text}
            step.reasoning = "Dispatching claim to the plan-query-execute-interpret-reflect loop."

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

            # Pick up any model text as reasoning, log tool calls, then execute them.
            reasoning_text = _collect_text(response.content)
            tool_use_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]

            if not tool_use_blocks:
                # Model stopped without finalizing. Log and break so we fall into
                # the fallback below instead of looping on empty responses.
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
                        step.input_data = tool_input
                        step.reasoning = reasoning_text or "Model emitted final verdict."
                        step.output_data = {"verdict": tool_input.get("verdict")}
                    tool_results_block.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": "Verdict recorded.",
                    })
                    finalized = True
                    continue

                tool = self._tools_by_name.get(name)
                stage = "query" if name == self.schema_tool.name else "execute"
                with self.trace_collector.start_step(self.name, stage) as step:
                    step.input_data = {"tool": name, "args": tool_input}
                    step.reasoning = reasoning_text if reasoning_text else ""
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
            # defensive insufficient_evidence verdict rather than crashing.
            fallback = insufficient(
                claim_text=claim_text,
                reason="Verifier exhausted its reasoning budget without reaching a verdict.",
                confidence="low",
                evidence=[Evidence(kind="claim", id=claim_text[:60])],
            )
            fallback.reasoning = "Verifier did not emit finalize_verdict within the step budget."
            return fallback

        return self._build_result(claim_text, final_input, tool_history)

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

        evidence = self._build_evidence(tool_history, files)

        if verdict == "contradicted":
            if not correct_value:
                # Contract would otherwise raise; keep an informative message.
                correct_value = _infer_correct_value(tool_history) or "not stated by verifier"
            return contradicted(
                claim_text=claim_text,
                correct_value=correct_value,
                evidence=evidence,
                reasoning=reasoning,
                confidence=confidence,
                severity=severity or "high",
                limitation=limitation,
            )
        if verdict == "supported":
            if not evidence:
                evidence = [Evidence(kind="claim", id=claim_text[:60])]
            return supported(
                claim_text=claim_text,
                evidence=evidence,
                reasoning=reasoning,
                confidence=confidence,
                severity=severity or "none",
                limitation=limitation,
            )
        return insufficient(
            claim_text=claim_text,
            reason=limitation or reasoning or "The data does not record what the claim requires.",
            confidence=confidence,
            severity=severity or "none",
            evidence=evidence,
        )

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


def _collect_text(blocks) -> str:
    chunks = [b.text for b in blocks if getattr(b, "type", None) == "text"]
    return " ".join(c.strip() for c in chunks if c and c.strip())


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
