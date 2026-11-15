"""Base class for all agents.

Handles the three things every agent needs:
  1. An Anthropic client (shared singleton from config.get_client()).
  2. A shared TraceCollector so every step lands in one audit trail.
  3. Retry logic on transient API errors (rate limits, overloads, timeouts).

Subclasses implement their own run() method and call self.call_llm() /
self.log_step() as needed.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from config import MAX_RETRIES, MODEL, get_client
from core.trace import TraceCollector, TraceEntry

logger = logging.getLogger(__name__)

_TRANSIENT_STATUSES = {408, 409, 429, 500, 502, 503, 504, 529}


class BaseAgent:
    def __init__(
        self,
        name: str,
        trace_collector: Optional[TraceCollector] = None,
        model: str = MODEL,
    ) -> None:
        self.name = name
        self.trace_collector = trace_collector or TraceCollector()
        self.model = model
        self.client = get_client()

    # ---------------------------------------------------------- Anthropic call

    def call_llm(
        self,
        system: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        max_tokens: int = 2048,
    ):
        """Send a Messages API request with retry on transient failures.

        The 2.x anthropic SDK no longer accepts temperature as a top-level kwarg,
        so we omit it. Deterministic verification relies on the tool computations,
        not on sampling settings.
        """
        last_err: Optional[Exception] = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "system": system,
                    "messages": messages,
                    "max_tokens": max_tokens,
                }
                if tools:
                    kwargs["tools"] = tools
                return self.client.messages.create(**kwargs)
            except Exception as e:  # noqa: BLE001
                last_err = e
                status = getattr(e, "status_code", None)
                detail = f"attempt {attempt + 1}/{MAX_RETRIES + 1} failed: {type(e).__name__}"
                if isinstance(status, int):
                    detail += f" (HTTP {status})"
                logger.warning("%s", detail)
                if attempt >= MAX_RETRIES or not _is_transient(e):
                    logger.error(
                        "model provider call failed after %d attempt(s)",
                        attempt + 1,
                        exc_info=True,
                    )
                    raise
                time.sleep(2 ** attempt)
        assert last_err is not None
        raise last_err

    # ------------------------------------------------------------- bookkeeping

    def log_step(
        self,
        stage: str,
        input_data: Any = None,
        output_data: Any = None,
        reasoning: str = "",
        tool_calls: Optional[list[dict]] = None,
        duration_ms: float = 0.0,
    ) -> TraceEntry:
        from datetime import datetime, timezone

        entry = TraceEntry(
            agent_name=self.name,
            stage=stage,
            input_data=input_data,
            output_data=output_data,
            reasoning=reasoning,
            tool_calls=list(tool_calls or []),
            duration_ms=duration_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self.trace_collector.add(entry)
        return entry

    def get_trace(self) -> list[TraceEntry]:
        return list(self.trace_collector.entries)


def _is_transient(err: Exception) -> bool:
    """Heuristic: anthropic APIStatusError subclasses carry .status_code."""
    status = getattr(err, "status_code", None)
    if isinstance(status, int) and status in _TRANSIENT_STATUSES:
        return True
    # Also treat connection/timeout errors as transient.
    name = type(err).__name__.lower()
    return any(k in name for k in ("timeout", "connection", "apiconnection", "ratelimit", "overload"))
