"""Tests for database initialization and the ORM schema."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reconcile.models.db_models import NotificationLog, RunLog

pytestmark = pytest.mark.unit


def test_init_db_creates_all_tables(db_engine: object) -> None:
    inspector = inspect(db_engine)
    tables = set(inspector.get_table_names())
    assert {"run_log", "audit_log", "notification_log", "exception_log"} <= tables


def test_run_log_insert_and_query(db_session: Session) -> None:
    run = RunLog(
        id="run-1",
        started_at=datetime.now(UTC),
        status="running",
        orders_count=14,
        settlements_count=12,
    )
    db_session.add(run)
    db_session.commit()

    fetched = db_session.get(RunLog, "run-1")
    assert fetched is not None
    assert fetched.orders_count == 14


def test_notification_unique_constraint(db_session: Session) -> None:
    common = {
        "run_id": "run-1",
        "mismatch_key": "key-abc",
        "recipient_role": "STORE_MANAGER",
        "recipient_email": "manager@demo.local",
        "channel": "EMAIL",
        "status": "SENT",
    }
    db_session.add(NotificationLog(**common))
    db_session.commit()

    db_session.add(NotificationLog(**common))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    rows = db_session.scalars(select(NotificationLog)).all()
    assert len(rows) == 1
