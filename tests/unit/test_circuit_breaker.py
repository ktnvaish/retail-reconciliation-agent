"""Tests for circuit breaking and idempotent dispatch via NotificationService."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from reconcile.config import ResilienceConfig
from reconcile.models.domain import NotificationStatus, RecipientRole
from reconcile.notifications.base import SendRequest, SendResult, TransientNotifyError
from reconcile.notifications.circuit_breaker import build_circuit_breaker
from reconcile.notifications.service import NotificationService

pytestmark = pytest.mark.unit

FAST_RESILIENCE = ResilienceConfig(
    email_retry_attempts=3,
    email_retry_min_seconds=0.0,
    email_retry_max_seconds=0.0,
    circuit_breaker_fail_max=3,
    circuit_breaker_reset_seconds=30,
)


class _AlwaysFails:
    name = "always-fails"

    def __init__(self) -> None:
        self.calls = 0

    def send(self, request: SendRequest) -> SendResult:
        self.calls += 1
        raise TransientNotifyError("boom")


class _Records:
    name = "records"

    def __init__(self) -> None:
        self.sent: list[SendRequest] = []

    def send(self, request: SendRequest) -> SendResult:
        self.sent.append(request)
        return SendResult(status=NotificationStatus.SENT, provider_id="ok")


def _service(notifier: object, session_factory: sessionmaker[Session]) -> NotificationService:
    breaker = build_circuit_breaker(name="test", fail_max=3, reset_timeout=30)
    return NotificationService(
        notifier=notifier,  # type: ignore[arg-type]
        breaker=breaker,
        resilience=FAST_RESILIENCE,
        session_factory=session_factory,
    )


def _dispatch(service: NotificationService, *, key: str = "k1") -> SendResult:
    return service.dispatch(
        run_id="run-1",
        mismatch_key=key,
        recipient_role=RecipientRole.PAYMENT_GATEWAY,
        recipient_email="pg@demo.local",
        subject="subject",
        body="body",
    )


def test_breaker_opens_after_repeated_failures(session_factory: sessionmaker[Session]) -> None:
    notifier = _AlwaysFails()
    service = _service(notifier, session_factory)

    # The first dispatch retries up to the attempt limit, tripping the breaker.
    first = _dispatch(service)
    assert first.status in {NotificationStatus.FAILED, NotificationStatus.SKIPPED}
    assert notifier.calls == 3  # three retries before the breaker opened
    assert "open" in service.breaker_state

    # A subsequent dispatch is short-circuited without touching the notifier.
    second = _dispatch(service, key="k2")
    assert second.status is NotificationStatus.SKIPPED
    assert second.reason == "circuit_open"
    assert notifier.calls == 3


def test_successful_dispatch_records_notification(session_factory: sessionmaker[Session]) -> None:
    notifier = _Records()
    service = _service(notifier, session_factory)
    result = _dispatch(service)
    assert result.status is NotificationStatus.SENT
    assert len(notifier.sent) == 1


def test_duplicate_dispatch_is_skipped(session_factory: sessionmaker[Session]) -> None:
    notifier = _Records()
    service = _service(notifier, session_factory)

    first = _dispatch(service, key="dup")
    second = _dispatch(service, key="dup")

    assert first.status is NotificationStatus.SENT
    assert second.status is NotificationStatus.SKIPPED
    assert second.reason == "duplicate"
    assert len(notifier.sent) == 1  # not sent twice
