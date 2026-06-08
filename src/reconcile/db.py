"""Database engine, session management, and schema initialization.

A single SQLite file backs all durable state. The engine is configured for safe
use from FastAPI's threadpool, with foreign keys and WAL journaling enabled.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from reconcile.config import AppSettings, get_settings
from reconcile.models.db_models import Base

_SQLITE_PREFIX = "sqlite:///"


def ensure_runtime_dirs(settings: AppSettings) -> None:
    """Create the runtime data directory, incidents directory, and DB parent dir."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.incidents_dir.mkdir(parents=True, exist_ok=True)
    db_path = _sqlite_path(settings.database_url)
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)


def _sqlite_path(database_url: str) -> Path | None:
    """Extract the filesystem path from a ``sqlite:///`` URL, if applicable."""
    if database_url.startswith(_SQLITE_PREFIX):
        return Path(database_url[len(_SQLITE_PREFIX) :])
    return None


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    """Enable foreign keys and WAL journaling for SQLite connections."""
    # Guard: only apply to SQLite (the DB-API connection exposes ``execute``).
    module = type(dbapi_connection).__module__
    if "sqlite3" not in module:
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def create_db_engine(settings: AppSettings) -> Engine:
    """Create a SQLAlchemy engine from settings, ensuring runtime dirs exist."""
    ensure_runtime_dirs(settings)
    connect_args: dict[str, Any] = {}
    if settings.database_url.startswith(_SQLITE_PREFIX):
        connect_args["check_same_thread"] = False
    return create_engine(
        settings.database_url,
        future=True,
        connect_args=connect_args,
    )


def init_db(engine: Engine) -> None:
    """Create all tables if they do not already exist."""
    Base.metadata.create_all(engine)


@functools.lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide engine (cached), creating runtime dirs as needed."""
    return create_db_engine(get_settings())


@functools.lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return a cached session factory bound to the process-wide engine."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session scope: commit on success, rollback on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
