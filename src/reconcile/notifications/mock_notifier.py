"""Mock notifier: captures emails to an append-only outbox instead of sending.

This is the default for local development, tests, and any demo where real
delivery is undesirable. Every "sent" email is appended as a JSON line to
``data/runtime/mock_outbox.jsonl`` and logged, so the full pipeline (and the
exact email content) is observable without external services.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from reconcile.logging_setup import get_logger
from reconcile.models.domain import NotificationStatus
from reconcile.notifications.base import SendRequest, SendResult

_log = get_logger("notifier.mock")


class MockNotifier:
    """A notifier that records emails to a JSONL outbox file."""

    name = "mock"

    def __init__(self, outbox_path: Path) -> None:
        self._outbox_path = outbox_path

    def send(self, request: SendRequest) -> SendResult:
        self._outbox_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "run_id": request.run_id,
            "mismatch_key": request.mismatch_key,
            "to": request.to,
            "role": request.recipient_role.value,
            "subject": request.subject,
            "body": request.body,
        }
        with self._outbox_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

        provider_id = f"mock-{request.mismatch_key[:12]}"
        _log.info("email_captured", to=request.to, subject=request.subject, provider_id=provider_id)
        return SendResult(status=NotificationStatus.SENT, provider_id=provider_id)
