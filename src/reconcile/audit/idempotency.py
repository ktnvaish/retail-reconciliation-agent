"""Idempotency helpers backed by the notification log and run log.

Two levels of idempotency:

* **Notification level** — ``(mismatch_key, recipient_email)`` is unique, so the
  same routed exception is never emailed twice. ``already_notified`` checks for a
  prior successful send; ``record_notification`` upserts the attempt outcome.
* **Run level** — ``input_hash`` over the two uploaded files lets a caller detect
  that an identical pair of files was already processed.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from reconcile.models.db_models import NotificationLog, RunLog
from reconcile.models.domain import NotificationChannel, NotificationStatus, RecipientRole


def compute_input_hash(orders_bytes: bytes, settlements_bytes: bytes) -> str:
    """Stable SHA-256 over the two input files (order matters)."""
    digest = hashlib.sha256()
    digest.update(orders_bytes)
    digest.update(b"|")
    digest.update(settlements_bytes)
    return digest.hexdigest()


def find_completed_run_by_hash(session: Session, input_hash: str) -> RunLog | None:
    """Return a prior completed run for the same input hash, if any."""
    stmt = (
        select(RunLog)
        .where(RunLog.input_hash == input_hash, RunLog.status == "completed")
        .order_by(RunLog.started_at.desc())
    )
    return session.scalars(stmt).first()


def already_notified(session: Session, mismatch_key: str, recipient_email: str) -> bool:
    """True if a *successful* notification already exists for this key + recipient."""
    stmt = select(NotificationLog).where(
        NotificationLog.mismatch_key == mismatch_key,
        NotificationLog.recipient_email == recipient_email,
        NotificationLog.status == NotificationStatus.SENT.value,
    )
    return session.scalar(stmt) is not None


def record_notification(
    session: Session,
    *,
    run_id: str,
    mismatch_key: str,
    recipient_role: RecipientRole,
    recipient_email: str,
    status: NotificationStatus,
    channel: NotificationChannel = NotificationChannel.EMAIL,
    error: str | None = None,
) -> None:
    """Upsert the outcome of a notification attempt.

    Upsert (rather than insert) keeps the ``(mismatch_key, recipient_email)``
    uniqueness invariant while allowing a previously failed attempt to be
    re-recorded as sent on a later run. The caller is responsible for committing.
    """
    existing = session.scalar(
        select(NotificationLog).where(
            NotificationLog.mismatch_key == mismatch_key,
            NotificationLog.recipient_email == recipient_email,
        )
    )
    if existing is not None:
        existing.run_id = run_id
        existing.recipient_role = recipient_role.value
        existing.status = status.value
        existing.channel = channel.value
        existing.error = error
        existing.sent_at = datetime.now(UTC)
        return

    session.add(
        NotificationLog(
            run_id=run_id,
            mismatch_key=mismatch_key,
            recipient_role=recipient_role.value,
            recipient_email=recipient_email,
            channel=channel.value,
            status=status.value,
            error=error,
        )
    )
