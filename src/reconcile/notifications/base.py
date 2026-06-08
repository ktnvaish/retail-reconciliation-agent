"""Notifier protocol and shared types.

A *notifier* knows only how to send one email. Resilience (retry, circuit
breaking), idempotency, and audit recording are layered on top by
:class:`~reconcile.notifications.service.NotificationService` so that each
notifier implementation stays small and easy to test.

Errors are classified so the retry policy can distinguish *transient* failures
(network blips, 5xx, timeouts) — worth retrying — from *permanent* ones (bad
credentials, 4xx validation) — which should fail fast.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from reconcile.models.domain import NotificationChannel, NotificationStatus, RecipientRole


class NotifyError(Exception):
    """Base class for notifier failures."""


class TransientNotifyError(NotifyError):
    """A retryable failure (network error, timeout, 5xx)."""


class PermanentNotifyError(NotifyError):
    """A non-retryable failure (auth error, invalid request, 4xx)."""


class SendRequest(BaseModel):
    """An immutable request to send one notification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    to: str
    subject: str
    body: str
    recipient_role: RecipientRole
    mismatch_key: str
    run_id: str
    channel: NotificationChannel = NotificationChannel.EMAIL


class SendResult(BaseModel):
    """The outcome of attempting to send a notification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: NotificationStatus
    provider_id: str | None = None
    error: str | None = None
    reason: str | None = None  # e.g. "duplicate", "circuit_open"

    @property
    def delivered(self) -> bool:
        return self.status is NotificationStatus.SENT


@runtime_checkable
class Notifier(Protocol):
    """Anything that can send a :class:`SendRequest`."""

    name: str

    def send(self, request: SendRequest) -> SendResult: ...
