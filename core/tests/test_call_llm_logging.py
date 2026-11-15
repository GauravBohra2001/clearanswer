"""Tests for model-provider failure logging in BaseAgent.call_llm."""
import logging

import pytest

from agents import base as base_mod


class _StatusError(Exception):
    """Stand-in for an anthropic APIStatusError carrying a status_code."""

    def __init__(self, status_code: int, message: str = "boom"):
        super().__init__(message)
        self.status_code = status_code


def _make_agent(outcomes: list):
    """Build a BaseAgent without touching the real Anthropic client.

    Bypasses __init__ (which requires a valid API key) and injects a stub
    client whose messages.create pops from `outcomes`: exceptions are raised,
    anything else is returned.
    """
    agent = base_mod.BaseAgent.__new__(base_mod.BaseAgent)
    agent.name = "stub"
    agent.model = "stub-model"

    class _Messages:
        def create(self, **kwargs):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class _Client:
        messages = _Messages()

    agent.client = _Client()
    return agent


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Skip real backoff delays so the retry loop runs instantly."""
    monkeypatch.setattr(base_mod.time, "sleep", lambda s: None)


def test_transient_failures_then_success_log_one_warning_each(caplog):
    ok = object()
    agent = _make_agent([_StatusError(429), _StatusError(429), ok])

    with caplog.at_level(logging.WARNING, logger="agents.base"):
        result = agent.call_llm(system="s", messages=[{"role": "user", "content": "hi"}])

    assert result is ok
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert all("429" in r.getMessage() for r in warnings)
    assert not any(r.levelno == logging.ERROR for r in caplog.records)


def test_always_failing_transient_logs_single_error_with_traceback(caplog):
    agent = _make_agent([_StatusError(429)] * (base_mod.MAX_RETRIES + 1))

    with caplog.at_level(logging.WARNING, logger="agents.base"):
        with pytest.raises(_StatusError):
            agent.call_llm(system="s", messages=[{"role": "user", "content": "hi"}])

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None
    assert isinstance(errors[0].exc_info[1], _StatusError)


def test_non_transient_error_fails_fast_with_single_error(caplog):
    agent = _make_agent([_StatusError(401)])

    with caplog.at_level(logging.WARNING, logger="agents.base"):
        with pytest.raises(_StatusError):
            agent.call_llm(system="s", messages=[{"role": "user", "content": "hi"}])

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(warnings) == 1  # failed fast: only one attempt
    assert len(errors) == 1
    assert isinstance(errors[0].exc_info[1], _StatusError)
