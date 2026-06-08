"""SQLAlchemy ORM models for local persistence.

Four tables back the system's durable state in a single SQLite file:

* ``run_log`` — one row per reconciliation run.
* ``audit_log`` — append-only, typed event stream per run.
* ``notification_log`` — one row per email attempt, with a unique
  ``(mismatch_key, recipient_email)`` index that makes "do not double-notify" a
  database invariant.
* ``exception_log`` — open/resolved lifecycle of each exception across runs.

Enum values are stored as their string ``.value`` to keep the schema decoupled
from the Python enum definitions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class RunLog(Base):
    """One row per agent invocation."""

    __tablename__ = "run_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    input_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    settlements_count: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class AuditLog(Base):
    """Append-only, typed event stream. Never updated — only inserted."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class NotificationLog(Base):
    """One row per email attempt. Unique on ``(mismatch_key, recipient_email)``."""

    __tablename__ = "notification_log"
    __table_args__ = (
        UniqueConstraint(
            "mismatch_key",
            "recipient_email",
            name="uq_notification_mismatch_recipient",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    mismatch_key: Mapped[str] = mapped_column(String(40), index=True)
    recipient_role: Mapped[str] = mapped_column(String(32))
    recipient_email: Mapped[str] = mapped_column(String(255))
    channel: Mapped[str] = mapped_column(String(16), default="EMAIL")
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ExceptionLog(Base):
    """Open/resolved lifecycle of an exception across runs.

    Keyed by ``mismatch_key`` so the verifier and the planner's history input can
    track a routed exception over time.
    """

    __tablename__ = "exception_log"

    mismatch_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    reason: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="OPEN")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
