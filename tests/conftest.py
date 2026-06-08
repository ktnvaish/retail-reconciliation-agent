"""Shared pytest fixtures.

Fixtures here construct *isolated* settings (temp data dir + temp SQLite) so
tests never touch a developer's real ``.env`` or runtime database. The LLM and
notifier always default to their offline/mock implementations.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from reconcile.config import AppSettings, load_app_config
from reconcile.db import create_db_engine, init_db

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = REPO_ROOT / "data" / "samples"
CONFIG_PATH = REPO_ROOT / "config" / "settings.yaml"


@pytest.fixture
def samples_dir() -> Path:
    """Path to the committed sample data directory."""
    return SAMPLES_DIR


@pytest.fixture
def make_settings(tmp_path: Path) -> Callable[..., AppSettings]:
    """Factory for isolated :class:`AppSettings` backed by a temp directory."""

    def _make(**overrides: Any) -> AppSettings:
        runtime = tmp_path / "runtime"
        base: dict[str, Any] = {
            "data_dir": runtime,
            "database_url": f"sqlite:///{(runtime / 'test.db').as_posix()}",
            "config_path": CONFIG_PATH,
            "mock_llm": True,
            "notifier": "mock",
        }
        base.update(overrides)
        # _env_file=None disables .env loading so tests are deterministic.
        return AppSettings(_env_file=None, **base)

    return _make


@pytest.fixture
def settings(make_settings: Callable[..., AppSettings]) -> AppSettings:
    """Default isolated settings."""
    return make_settings()


@pytest.fixture
def app_config(settings: AppSettings) -> Any:
    """Loaded business configuration from the committed YAML."""
    return load_app_config(settings)


@pytest.fixture
def db_engine(settings: AppSettings) -> Iterator[Engine]:
    """An initialized SQLite engine on a temp database."""
    engine = create_db_engine(settings)
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session bound to the temp engine."""
    factory = sessionmaker(bind=db_engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def session_factory(db_engine: Engine) -> sessionmaker[Session]:
    """A session factory bound to the temp engine (for services)."""
    return sessionmaker(bind=db_engine, expire_on_commit=False, future=True)
