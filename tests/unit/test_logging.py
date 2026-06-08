"""Tests for structured logging setup and run-id context binding."""

from __future__ import annotations

import json

import pytest
import structlog

from reconcile.logging_setup import (
    configure_logging,
    get_logger,
    new_run_id,
    run_context,
)

pytestmark = pytest.mark.unit


def test_new_run_id_is_uuid_like() -> None:
    run_id = new_run_id()
    assert run_id.count("-") == 4
    assert len(run_id) == 36


def test_run_context_binds_and_clears(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    log = get_logger("test")

    with run_context() as run_id:
        log.info("inside")
    log.info("outside")

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    inside = json.loads(lines[0])
    outside = json.loads(lines[1])

    assert inside["run_id"] == run_id
    assert inside["event"] == "inside"
    assert inside["component"] == "test"
    assert "run_id" not in outside  # context cleared on exit


def test_log_level_filtering(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING")
    log = get_logger()
    log.info("suppressed")
    log.warning("shown")

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    events = [json.loads(line)["event"] for line in lines]
    assert "suppressed" not in events
    assert "shown" in events
    # Reset to INFO so later tests are unaffected by the cached logger config.
    configure_logging("INFO")
    structlog.contextvars.clear_contextvars()
