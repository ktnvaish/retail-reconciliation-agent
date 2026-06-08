"""Notifier factory: pick an implementation from settings."""

from __future__ import annotations

from reconcile.config import AppSettings
from reconcile.notifications.base import Notifier
from reconcile.notifications.mock_notifier import MockNotifier
from reconcile.notifications.resend_notifier import ResendNotifier
from reconcile.notifications.smtp_notifier import SmtpNotifier


def build_notifier(settings: AppSettings) -> Notifier:
    """Construct the notifier selected by ``settings.notifier``."""
    match settings.notifier:
        case "mock":
            return MockNotifier(settings.mock_outbox_path)
        case "resend":
            return ResendNotifier(settings.resend_api_key, settings.resend_from)
        case "smtp":
            return SmtpNotifier(
                host=settings.smtp_host,
                port=settings.smtp_port,
                user=settings.smtp_user,
                password=settings.smtp_password,
                sender=settings.smtp_from,
            )
