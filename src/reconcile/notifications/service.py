"""Notification service: resilient, idempotent, audited email dispatch.

Composes the pieces so callers (the agent's dispatch node, the admin notifier)
get a single ``dispatch`` call that:

1. skips if this ``(mismatch_key, recipient)`` was already sent (idempotency),
2. sends via the circuit breaker with exponential-backoff retries,
3. records the outcome in ``notification_log``,

returning a :class:`SendResult` describing what happened (sent / skipped /
failed). It never raises for an expected delivery failure.
"""

from __future__ import annotations

from collections.abc import Callable

import pybreaker
from sqlalchemy.orm import Session

from reconcile.audit.idempotency import already_notified, record_notification
from reconcile.config import AppSettings, ResilienceConfig
from reconcile.logging_setup import get_logger
from reconcile.models.domain import NotificationStatus, RecipientRole
from reconcile.notifications.base import (
    Notifier,
    NotifyError,
    SendRequest,
    SendResult,
    TransientNotifyError,
)
from reconcile.notifications.circuit_breaker import build_circuit_breaker
from reconcile.notifications.factory import build_notifier
from reconcile.notifications.retry import call_with_retry

_log = get_logger("notification_service")


class NotificationService:
    """Resilient, idempotent, audited notification dispatch."""

    def __init__(
        self,
        *,
        notifier: Notifier,
        breaker: pybreaker.CircuitBreaker,
        resilience: ResilienceConfig,
        session_factory: Callable[[], Session],
    ) -> None:
        self._notifier = notifier
        self._breaker = breaker
        self._resilience = resilience
        self._session_factory = session_factory

    def dispatch(
        self,
        *,
        run_id: str,
        mismatch_key: str,
        recipient_role: RecipientRole,
        recipient_email: str,
        subject: str,
        body: str,
    ) -> SendResult:
        """Send one notification, honoring idempotency and resilience policies."""
        with self._session_factory() as session:
            if already_notified(session, mismatch_key, recipient_email):
                _log.info(
                    "notification_skipped_duplicate", mismatch_key=mismatch_key, to=recipient_email
                )
                return SendResult(status=NotificationStatus.SKIPPED, reason="duplicate")

        request = SendRequest(
            to=recipient_email,
            subject=subject,
            body=body,
            recipient_role=recipient_role,
            mismatch_key=mismatch_key,
            run_id=run_id,
        )
        result = self._send(request)
        self._record(run_id, mismatch_key, recipient_role, recipient_email, result)
        return result

    def _send(self, request: SendRequest) -> SendResult:
        def attempt() -> SendResult:
            return self._breaker.call(self._notifier.send, request)

        try:
            return call_with_retry(
                attempt,
                attempts=self._resilience.email_retry_attempts,
                min_seconds=self._resilience.email_retry_min_seconds,
                max_seconds=self._resilience.email_retry_max_seconds,
                retry_on=TransientNotifyError,
            )
        except pybreaker.CircuitBreakerError:
            _log.warning("notification_circuit_open", to=request.to)
            return SendResult(status=NotificationStatus.SKIPPED, reason="circuit_open")
        except NotifyError as exc:
            _log.warning("notification_failed", to=request.to, error=str(exc))
            return SendResult(status=NotificationStatus.FAILED, error=str(exc))

    def _record(
        self,
        run_id: str,
        mismatch_key: str,
        recipient_role: RecipientRole,
        recipient_email: str,
        result: SendResult,
    ) -> None:
        with self._session_factory() as session:
            record_notification(
                session,
                run_id=run_id,
                mismatch_key=mismatch_key,
                recipient_role=recipient_role,
                recipient_email=recipient_email,
                status=result.status,
                error=result.error,
            )
            session.commit()

    @property
    def breaker_state(self) -> str:
        return str(self._breaker.current_state)

    @property
    def breaker_fail_count(self) -> int:
        return int(self._breaker.fail_counter)


def build_notification_service(
    settings: AppSettings,
    resilience: ResilienceConfig,
    session_factory: Callable[[], Session],
) -> NotificationService:
    """Wire a notification service from settings and resilience config."""
    breaker = build_circuit_breaker(
        name="notifier",
        fail_max=resilience.circuit_breaker_fail_max,
        reset_timeout=resilience.circuit_breaker_reset_seconds,
    )
    return NotificationService(
        notifier=build_notifier(settings),
        breaker=breaker,
        resilience=resilience,
        session_factory=session_factory,
    )
