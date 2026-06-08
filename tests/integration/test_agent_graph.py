"""End-to-end agent graph tests using the mock LLM and mock notifier."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from reconcile.agent import ReconciliationAgent, build_agent
from reconcile.config import AppConfig, AppSettings
from reconcile.models.db_models import AuditLog, NotificationLog
from reconcile.parsers import read_orders, read_settlements

pytestmark = pytest.mark.integration

AS_OF = date(2026, 6, 8)


@pytest.fixture
def agent(
    settings: AppSettings,
    app_config: AppConfig,
    session_factory: sessionmaker[Session],
) -> ReconciliationAgent:
    return build_agent(settings, app_config, session_factory)


def _load_samples(samples_dir: Path) -> tuple[list, list]:
    orders = read_orders(samples_dir / "orders_sample.csv")
    settlements = read_settlements(samples_dir / "settlements_sample.csv")
    return orders, settlements


def test_full_run_on_samples(
    agent: ReconciliationAgent,
    settings: AppSettings,
    session_factory: sessionmaker[Session],
    samples_dir: Path,
) -> None:
    orders, settlements = _load_samples(samples_dir)
    outcome = agent.run(orders=orders, settlements=settlements, as_of_date=AS_OF)

    assert outcome.status == "completed"
    # 6 deterministic matches + 1 fuzzy auto-applied (O1011 <-> S2011).
    assert outcome.summary["matched"] == 7
    assert outcome.fuzzy_auto_applied == 1

    reasons = outcome.summary["exceptions_by_reason"]
    assert reasons["CASH_MISSING"] == 1
    assert reasons["ONLINE_MISSING"] == 1  # O1011 was fuzzy-matched away
    assert reasons["LATE_SETTLEMENT"] == 1
    assert reasons["AMOUNT_SHORT"] == 1
    assert reasons["AMOUNT_EXCESS"] == 1
    assert reasons["DUPLICATE_SETTLEMENT"] == 1
    assert reasons["UNMATCHED_SETTLEMENT"] == 1
    assert reasons["ORDER_SUM_MISMATCH"] == 1

    # The within-SLA late settlement should produce a WAIT (no email).
    assert outcome.summary["actions"].get("WAIT") == 1

    # Emails went to the mock outbox; the late-settlement WAIT sent nothing.
    outbox = settings.mock_outbox_path
    sent_lines = outbox.read_text(encoding="utf-8").splitlines()
    assert len(sent_lines) == 11
    assert outcome.summary["notifications"].get("SENT") == 11

    # Audit + notification rows were persisted.
    with session_factory() as session:
        audit_count = session.scalar(select(func.count()).select_from(AuditLog))
        notif_count = session.scalar(select(func.count()).select_from(NotificationLog))
    assert audit_count is not None and audit_count > 0
    assert notif_count == 11


def test_rerun_is_idempotent(
    agent: ReconciliationAgent,
    settings: AppSettings,
    samples_dir: Path,
) -> None:
    orders, settlements = _load_samples(samples_dir)
    agent.run(orders=orders, settlements=settlements, as_of_date=AS_OF)
    first_outbox = settings.mock_outbox_path.read_text(encoding="utf-8").splitlines()

    second = agent.run(orders=orders, settlements=settlements, as_of_date=AS_OF)

    # No new emails were actually sent on the second run.
    second_outbox = settings.mock_outbox_path.read_text(encoding="utf-8").splitlines()
    assert len(second_outbox) == len(first_outbox)
    assert second.summary["notifications"].get("SKIPPED") == 11


def test_dry_run_sends_nothing(
    agent: ReconciliationAgent,
    settings: AppSettings,
    samples_dir: Path,
) -> None:
    orders, settlements = _load_samples(samples_dir)
    outcome = agent.run(orders=orders, settlements=settlements, as_of_date=AS_OF, dry_run=True)

    assert not settings.mock_outbox_path.exists()
    assert outcome.summary["notifications"].get("SKIPPED") == 11
    assert outcome.summary["notifications"].get("SENT") is None
