"""Resend notifier: real email delivery over HTTPS.

Resend's HTTP API works from cloud environments where outbound SMTP (port 25) is
blocked, which makes it the default for the hosted Azure demo. API errors are
classified into transient vs permanent so the retry policy behaves sensibly.
"""

from __future__ import annotations

import resend

from reconcile.logging_setup import get_logger
from reconcile.models.domain import NotificationStatus
from reconcile.notifications.base import (
    PermanentNotifyError,
    SendRequest,
    SendResult,
    TransientNotifyError,
)

_log = get_logger("notifier.resend")

# HTTP statuses that will never succeed on retry.
_PERMANENT_STATUSES = {400, 401, 403, 404, 422}


class ResendNotifier:
    """A notifier backed by the Resend HTTP API."""

    name = "resend"

    def __init__(self, api_key: str, sender: str) -> None:
        if not api_key:
            raise ValueError("RESEND_API_KEY is required when NOTIFIER=resend")
        self._sender = sender
        resend.api_key = api_key

    def send(self, request: SendRequest) -> SendResult:
        params: resend.Emails.SendParams = {
            "from": self._sender,
            "to": [request.to],
            "subject": request.subject,
            "text": request.body,
        }
        try:
            response = resend.Emails.send(params)
        except Exception as exc:  # normalize any SDK error into our taxonomy
            raise _classify(exc) from exc

        provider_id = response.get("id")
        _log.info("email_sent", to=request.to, provider_id=provider_id)
        return SendResult(status=NotificationStatus.SENT, provider_id=provider_id)


def _classify(exc: Exception) -> Exception:
    """Map an arbitrary Resend SDK error to a transient/permanent notify error."""
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int) and status in _PERMANENT_STATUSES:
        return PermanentNotifyError(f"Resend permanent error ({status}): {exc}")
    return TransientNotifyError(f"Resend transient error: {exc}")
