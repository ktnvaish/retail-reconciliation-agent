"""Tests for idempotency helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from reconcile.audit.idempotency import (
    already_notified,
    compute_input_hash,
    find_completed_run_by_hash,
    record_notification,
)
from reconcile.models.db_models import NotificationLog, RunLog
from reconcile.models.domain import NotificationStatus, RecipientRole

pytestmark = pytest.mark.unit


def test_input_hash_is_deterministic_and_order_sensitive() -> None:
    a = compute_input_hash(b"orders", b"settlements")
    b = compute_input_hash(b"orders", b"settlements")
    c = compute_input_hash(b"settlements", b"orders")
    assert a == b
    assert a != c
    assert len(a) == 64


def test_record_then_already_notified(db_session: Session) -> None:
    assert not already_notified(db_session, "key1", "to@demo.local")
    record_notification(
        db_session,
        run_id="run-1",
        mismatch_key="key1",
        recipient_role=RecipientRole.STORE_MANAGER,
        recipient_email="to@demo.local",
        status=NotificationStatus.SENT,
    )
    db_session.commit()
    assert already_notified(db_session, "key1", "to@demo.local")


def test_record_notification_upserts_failed_then_sent(db_session: Session) -> None:
    record_notification(
        db_session,
        run_id="run-1",
        mismatch_key="key2",
        recipient_role=RecipientRole.BANK,
        recipient_email="bank@demo.local",
        status=NotificationStatus.FAILED,
        error="smtp down",
    )
    db_session.commit()
    assert not already_notified(db_session, "key2", "bank@demo.local")

    record_notification(
        db_session,
        run_id="run-2",
        mismatch_key="key2",
        recipient_role=RecipientRole.BANK,
        recipient_email="bank@demo.local",
        status=NotificationStatus.SENT,
    )
    db_session.commit()

    rows = db_session.scalars(select(NotificationLog)).all()
    assert len(rows) == 1  # upsert, not a second row
    assert rows[0].status == NotificationStatus.SENT.value
    assert already_notified(db_session, "key2", "bank@demo.local")


def test_find_completed_run_by_hash(db_session: Session) -> None:
    digest = compute_input_hash(b"o", b"s")
    db_session.add(
        RunLog(
            id="run-x",
            started_at=datetime.now(UTC),
            status="completed",
            input_hash=digest,
        )
    )
    db_session.commit()

    found = find_completed_run_by_hash(db_session, digest)
    assert found is not None
    assert found.id == "run-x"
    assert find_completed_run_by_hash(db_session, "nonexistent") is None
