"""Tests for the cross-run verifier."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from reconcile.agent.verifier import mark_resolved
from reconcile.models.db_models import ExceptionLog

pytestmark = pytest.mark.unit


def _seed(session: Session, mismatch_key: str, status: str) -> None:
    now = datetime.now(UTC)
    session.add(
        ExceptionLog(
            mismatch_key=mismatch_key,
            run_id="run-0",
            reason="CASH_MISSING",
            status=status,
            first_seen=now,
            last_seen=now,
        )
    )


def test_absent_open_exceptions_are_resolved(db_session: Session) -> None:
    _seed(db_session, "still-open", "OPEN")
    _seed(db_session, "now-gone", "OPEN")
    _seed(db_session, "already-resolved", "RESOLVED")
    db_session.commit()

    resolved = mark_resolved(db_session, run_id="run-1", current_keys={"still-open"})
    db_session.commit()

    assert resolved == 1
    rows = {row.mismatch_key: row.status for row in db_session.query(ExceptionLog).all()}
    assert rows["still-open"] == "OPEN"
    assert rows["now-gone"] == "RESOLVED"
    assert rows["already-resolved"] == "RESOLVED"


def test_nothing_resolved_when_all_present(db_session: Session) -> None:
    _seed(db_session, "k1", "OPEN")
    _seed(db_session, "k2", "ESCALATED")
    db_session.commit()

    resolved = mark_resolved(db_session, run_id="run-1", current_keys={"k1", "k2"})
    assert resolved == 0
