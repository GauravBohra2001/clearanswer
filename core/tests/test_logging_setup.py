"""Tests for core.logging_setup: idempotency, tagging, and key redaction."""
import logging
from logging.handlers import RotatingFileHandler

import pytest

import config
from core import logging_setup


@pytest.fixture(autouse=True)
def _clean_root_logger():
    """Save/restore the root logger's handlers and level around each test."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    for handler in root.handlers:
        root.removeHandler(handler)
        handler.close()
    root.setLevel(saved_level)
    logging_setup._configured = False


def _log_file(tmp_path):
    return tmp_path / "clearanswer.log"


def test_double_setup_does_not_duplicate_records(tmp_path):
    logging_setup.setup_logging(log_dir=tmp_path)
    logging_setup.setup_logging(log_dir=tmp_path)

    root = logging.getLogger()
    # Count only the handlers setup_logging adds; pytest's own caplog /
    # live-log handlers also sit on the root logger during a test run.
    console = [h for h in root.handlers if type(h) is logging.StreamHandler]
    files = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(console) == 1  # one console handler, no duplicates
    assert len(files) == 1  # one rotating file handler, no duplicates

    logging.getLogger("test").info("hello-once")
    assert _log_file(tmp_path).read_text(encoding="utf-8").count("hello-once") == 1


def test_api_key_is_redacted_in_output_file(tmp_path, monkeypatch):
    fake_key = "sk-ant-test-fake-key-12345"
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", fake_key)

    logging_setup.setup_logging(log_dir=tmp_path)
    logging.getLogger("test").error(f"request failed with key {fake_key}")

    content = _log_file(tmp_path).read_text(encoding="utf-8")
    assert fake_key not in content
    assert "[REDACTED]" in content


def test_job_id_and_run_path_suffixes(tmp_path):
    logging_setup.setup_logging(log_dir=tmp_path)
    logger = logging.getLogger("test")
    logger.info("audit started", extra={"job_id": "abc123"})
    logger.info("audit done", extra={"run_path": "reports/claim.md"})

    content = _log_file(tmp_path).read_text(encoding="utf-8")
    assert "[job=abc123]" in content
    assert "[run=reports/claim.md]" in content


def test_plain_record_has_no_tag(tmp_path):
    logging_setup.setup_logging(log_dir=tmp_path)
    logging.getLogger("test").info("untagged line")

    content = _log_file(tmp_path).read_text(encoding="utf-8")
    assert "[job=" not in content
    assert "[run=" not in content
