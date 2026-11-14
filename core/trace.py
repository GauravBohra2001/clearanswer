"""Trace recording for agent runs.

Every step an agent takes — plan, query, execute, interpret, reflect, extract,
guard — becomes a TraceEntry. The TraceCollector owns the ordered list and can
serialize it to JSON (for audit.json evidence) or Markdown (for the live demo).

A step is the atomic unit of agent work. Use the start_step context manager so
timestamps and durations are captured consistently:

    with tc.start_step("verifier", "plan") as step:
        step.input_data = {"claim": claim_text}
        step.reasoning = "Need to check PAM50 subtype percentages"
        step.output_data = {"columns": ["PAM50Call_RNAseq"]}
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class TraceEntry:
    agent_name: str
    stage: str
    input_data: Any = None
    output_data: Any = None
    reasoning: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: str = ""


class TraceCollector:
    """Ordered log of agent steps. One per claim-check run, typically."""

    def __init__(self) -> None:
        self.entries: list[TraceEntry] = []

    def add(self, entry: TraceEntry) -> None:
        self.entries.append(entry)

    @contextmanager
    def start_step(self, agent_name: str, stage: str):
        """Capture timestamp and duration automatically.

        The yielded TraceEntry is mutable: assign input_data, output_data,
        reasoning and tool_calls on it inside the `with` block.
        """
        entry = TraceEntry(
            agent_name=agent_name,
            stage=stage,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        start = time.perf_counter()
        try:
            yield entry
        finally:
            entry.duration_ms = round((time.perf_counter() - start) * 1000.0, 3)
            self.entries.append(entry)

    def to_dict(self) -> list[dict]:
        return [asdict(e) for e in self.entries]

    def to_markdown(self) -> str:
        if not self.entries:
            return "_(no trace entries)_"
        lines = ["# Agent trace", ""]
        for i, e in enumerate(self.entries, 1):
            lines.append(f"## Step {i} · `{e.agent_name}` / `{e.stage}`")
            lines.append(f"- **When:** {e.timestamp}  **Duration:** {e.duration_ms} ms")
            if e.reasoning:
                lines.append(f"- **Reasoning:** {e.reasoning}")
            if e.input_data is not None:
                lines.append(f"- **Input:** `{_fmt(e.input_data)}`")
            if e.output_data is not None:
                lines.append(f"- **Output:** `{_fmt(e.output_data)}`")
            if e.tool_calls:
                lines.append(f"- **Tool calls:** {len(e.tool_calls)}")
                for tc in e.tool_calls:
                    lines.append(f"  - `{tc.get('name', '?')}` → {_fmt(tc.get('input'))}")
            lines.append("")
        return "\n".join(lines)


def _fmt(value: Any, limit: int = 240) -> str:
    text = repr(value)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text
