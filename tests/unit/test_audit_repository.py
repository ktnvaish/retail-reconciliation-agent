"""Tests for the audit repository."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from reconcile.audit.repository import AuditRepository

pytestmark = pytest.mark.unit


def test_start_and_finish_run(db_session: Session) -> None:
    repo = AuditRepository(db_session)
    repo.start_run("run-1", input_hash="hash", orders_count=14, settlements_count=12)
    db_session.commit()

    run = repo.get_run("run-1")
    assert run is not None
    assert run.status == "running"
    assert run.orders_count == 14

    repo.finish_run("run-1", status="completed", summary={"matched": 6})
    db_session.commit()

    run = repo.get_run("run-1")
    assert run is not None
    assert run.status == "completed"
    assert run.finished_at is not None
    assert run.summary_json == {"matched": 6}


def test_log_event_is_appended(db_session: Session) -> None:
    repo = AuditRepository(db_session)
    repo.start_run("run-1")
    repo.log_event("run-1", "reconcile_completed", status="ok", details={"n": 3})
    repo.log_event("run-1", "email_sent", action="EMAIL_PG", reason="ONLINE_MISSING")
    db_session.commit()

    events = repo.list_events("run-1")
    assert [e.event_type for e in events] == ["reconcile_completed", "email_sent"]
    assert events[1].action == "EMAIL_PG"


def test_upsert_exception_inserts_then_updates(db_session: Session) -> None:
    repo = AuditRepository(db_session)
    repo.upsert_exception(mismatch_key="k1", run_id="run-1", reason="CASH_MISSING", status="OPEN")
    db_session.commit()

    row = repo.get_open_exception("k1")
    assert row is not None
    assert row.status == "OPEN"
    first_seen = row.first_seen

    repo.upsert_exception(
        mismatch_key="k1", run_id="run-2", reason="CASH_MISSING", status="RESOLVED"
    )
    db_session.commit()

    row = repo.get_open_exception("k1")
    assert row is not None
    assert row.status == "RESOLVED"
    assert row.run_id == "run-2"
    assert row.first_seen == first_seen  # preserved across updates


def test_get_run_returns_none_for_unknown(db_session: Session) -> None:
    repo = AuditRepository(db_session)
    assert repo.get_run("missing") is None
