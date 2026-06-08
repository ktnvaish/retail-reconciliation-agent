"""Aggregate metrics for the ``/metrics`` endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from reconcile.models.db_models import ExceptionLog, NotificationLog, RunLog

if TYPE_CHECKING:
    from reconcile.app import AppContext


def build_metrics_snapshot(context: AppContext) -> dict[str, Any]:
    """Build a JSON-serializable metrics snapshot from the DB and live services."""
    with context.session_factory() as session:
        runs_total = session.scalar(select(func.count()).select_from(RunLog)) or 0
        reason_rows = session.execute(
            select(ExceptionLog.reason, func.count()).group_by(ExceptionLog.reason)
        ).all()
        status_rows = session.execute(
            select(NotificationLog.status, func.count()).group_by(NotificationLog.status)
        ).all()

    return {
        "runs_total": runs_total,
        "exceptions_by_reason": {row[0]: row[1] for row in reason_rows},
        "notifications": {row[0]: row[1] for row in status_rows},
        "incidents": context.deps.incidents.store.count_by_status(),
        "circuit_breaker": {
            "state": context.deps.notifications.breaker_state,
            "fail_count": context.deps.notifications.breaker_fail_count,
        },
    }
