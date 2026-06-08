"""Tests for notifier implementations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reconcile.models.domain import NotificationStatus, RecipientRole
from reconcile.notifications.base import (
    PermanentNotifyError,
    SendRequest,
    SendResult,
    TransientNotifyError,
)
from reconcile.notifications.mock_notifier import MockNotifier
from reconcile.notifications.resend_notifier import _classify

pytestmark = pytest.mark.unit


def _request(**overrides: object) -> SendRequest:
    base: dict[str, object] = {
        "to": "ops@demo.local",
        "subject": "Test subject",
        "body": "Test body",
        "recipient_role": RecipientRole.STORE_MANAGER,
        "mismatch_key": "abc123",
        "run_id": "run-1",
    }
    base.update(overrides)
    return SendRequest.model_validate(base)


def test_mock_notifier_writes_outbox(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox.jsonl"
    notifier = MockNotifier(outbox)
    result = notifier.send(_request(subject="Hello"))

    assert result.status is NotificationStatus.SENT
    assert result.delivered
    lines = outbox.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["subject"] == "Hello"
    assert record["to"] == "ops@demo.local"


def test_mock_notifier_appends(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox.jsonl"
    notifier = MockNotifier(outbox)
    notifier.send(_request(mismatch_key="k1"))
    notifier.send(_request(mismatch_key="k2"))
    assert len(outbox.read_text(encoding="utf-8").splitlines()) == 2


def test_send_result_delivered_flag() -> None:
    assert SendResult(status=NotificationStatus.SENT).delivered
    assert not SendResult(status=NotificationStatus.FAILED).delivered
    assert not SendResult(status=NotificationStatus.SKIPPED, reason="duplicate").delivered


class _FakeHttpError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"http {status_code}")
        self.status_code = status_code


def test_resend_classify_permanent() -> None:
    assert isinstance(_classify(_FakeHttpError(401)), PermanentNotifyError)
    assert isinstance(_classify(_FakeHttpError(422)), PermanentNotifyError)


def test_resend_classify_transient() -> None:
    assert isinstance(_classify(_FakeHttpError(500)), TransientNotifyError)
    assert isinstance(_classify(RuntimeError("network down")), TransientNotifyError)
