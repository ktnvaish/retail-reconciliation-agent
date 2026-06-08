"""SMTP notifier: real email delivery via an SMTP server (e.g. Gmail).

Useful for local testing with a Gmail App Password. Note that many cloud hosts
block outbound port 25/587; prefer Resend for the hosted demo.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from reconcile.logging_setup import get_logger
from reconcile.models.domain import NotificationStatus
from reconcile.notifications.base import (
    PermanentNotifyError,
    SendRequest,
    SendResult,
    TransientNotifyError,
)

_log = get_logger("notifier.smtp")
_TIMEOUT_SECONDS = 15


class SmtpNotifier:
    """A notifier that sends mail over SMTP with STARTTLS."""

    name = "smtp"

    def __init__(self, host: str, port: int, user: str, password: str, sender: str) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._sender = sender or user

    def send(self, request: SendRequest) -> SendResult:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = request.to
        message["Subject"] = request.subject
        message.set_content(request.body)

        try:
            with smtplib.SMTP(self._host, self._port, timeout=_TIMEOUT_SECONDS) as server:
                server.starttls()
                if self._user:
                    server.login(self._user, self._password)
                server.send_message(message)
        except smtplib.SMTPAuthenticationError as exc:
            raise PermanentNotifyError(f"SMTP authentication failed: {exc}") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise TransientNotifyError(f"SMTP send failed: {exc}") from exc

        _log.info("email_sent", to=request.to)
        return SendResult(status=NotificationStatus.SENT)
