"""Notification layer: notifiers, resilience, and the dispatch service."""

from reconcile.notifications.base import (
    Notifier,
    NotifyError,
    PermanentNotifyError,
    SendRequest,
    SendResult,
    TransientNotifyError,
)
from reconcile.notifications.factory import build_notifier
from reconcile.notifications.service import NotificationService, build_notification_service

__all__ = [
    "NotificationService",
    "Notifier",
    "NotifyError",
    "PermanentNotifyError",
    "SendRequest",
    "SendResult",
    "TransientNotifyError",
    "build_notification_service",
    "build_notifier",
]
