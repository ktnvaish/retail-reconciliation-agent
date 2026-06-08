"""Verifier: reconcile the exception lifecycle across runs.

After dispatch, any exception that was previously open but is *not* present in the
current run is considered resolved (e.g. a corrected settlements file was
uploaded). This is what lets a later run close out earlier exceptions.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from reconcile.models.db_models import ExceptionLog

_UNRESOLVED = ("OPEN", "AWAITING_RECHECK", "ESCALATED")


def mark_resolved(session: Session, *, run_id: str, current_keys: set[str]) -> int:
    """Mark previously-unresolved exceptions absent from this run as resolved.

    Returns the number of exceptions newly resolved. The caller commits.
    """
    stmt = select(ExceptionLog).where(ExceptionLog.status.in_(_UNRESOLVED))
    resolved = 0
    for row in session.scalars(stmt).all():
        if row.mismatch_key not in current_keys:
            row.status = "RESOLVED"
            row.last_seen = datetime.now(UTC)
            row.run_id = run_id
            resolved += 1
    return resolved
