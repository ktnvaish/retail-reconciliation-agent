"""Append-only audit repository.

Every significant event is written to ``audit_log`` *and* emitted as a structured
log line, so the audit trail and the telemetry stream stay in lock-step. The
repository also manages the ``run_log`` lifecycle and the cross-run
``exception_log``. Methods operate on the injected session; the caller commits.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from reconcile.logging_setup import get_logger
from reconcile.models.db_models import AuditLog, ExceptionLog, NotificationLog, RunLog

_log = get_logger("audit")


class AuditRepository:
    """Reads and writes the run, audit, and exception logs."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- run lifecycle ----------------------------------------------------- #

    def start_run(
        self,
        run_id: str,
        *,
        input_hash: str | None = None,
        orders_count: int = 0,
        settlements_count: int = 0,
    ) -> RunLog:
        run = RunLog(
            id=run_id,
            started_at=datetime.now(UTC),
            status="running",
            input_hash=input_hash,
            orders_count=orders_count,
            settlements_count=settlements_count,
        )
        self._session.add(run)
        _log.info("run_started", run_id=run_id, orders=orders_count, settlements=settlements_count)
        return run

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        summary: dict[str, Any] | None = None,
    ) -> None:
        run = self._session.get(RunLog, run_id)
        if run is not None:
            run.finished_at = datetime.now(UTC)
            run.status = status
            run.summary_json = summary
        _log.info("run_finished", run_id=run_id, status=status)

    # -- events ------------------------------------------------------------ #

    def log_event(
        self,
        run_id: str,
        event_type: str,
        *,
        order_id: str | None = None,
        action: str | None = None,
        reason: str | None = None,
        status: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append one typed audit event (and emit matching telemetry)."""
        self._session.add(
            AuditLog(
                run_id=run_id,
                ts=datetime.now(UTC),
                order_id=order_id,
                event_type=event_type,
                action=action,
                reason=reason,
                status=status,
                details=details,
            )
        )
        _log.info(
            event_type,
            run_id=run_id,
            order_id=order_id,
            action=action,
            reason=reason,
            status=status,
        )

    # -- exception lifecycle ---------------------------------------------- #

    def upsert_exception(
        self,
        *,
        mismatch_key: str,
        run_id: str,
        reason: str,
        status: str,
    ) -> None:
        """Insert or update the cross-run lifecycle row for an exception."""
        now = datetime.now(UTC)
        existing = self._session.get(ExceptionLog, mismatch_key)
        if existing is not None:
            existing.run_id = run_id
            existing.reason = reason
            existing.status = status
            existing.last_seen = now
            return
        self._session.add(
            ExceptionLog(
                mismatch_key=mismatch_key,
                run_id=run_id,
                reason=reason,
                status=status,
                first_seen=now,
                last_seen=now,
            )
        )

    def get_open_exception(self, mismatch_key: str) -> ExceptionLog | None:
        """Return the lifecycle row for a mismatch key, if present."""
        return self._session.get(ExceptionLog, mismatch_key)

    # -- queries ----------------------------------------------------------- #

    def get_run(self, run_id: str) -> RunLog | None:
        return self._session.get(RunLog, run_id)

    def list_events(self, run_id: str) -> list[AuditLog]:
        stmt = select(AuditLog).where(AuditLog.run_id == run_id).order_by(AuditLog.id)
        return list(self._session.scalars(stmt).all())

    def list_notifications(self, run_id: str) -> list[NotificationLog]:
        stmt = (
            select(NotificationLog)
            .where(NotificationLog.run_id == run_id)
            .order_by(NotificationLog.id)
        )
        return list(self._session.scalars(stmt).all())
