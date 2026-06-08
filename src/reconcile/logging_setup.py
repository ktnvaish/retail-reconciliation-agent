"""Structured logging setup.

Emits one JSON object per log line to stdout, which is ideal for ``jq`` locally
and for the Azure Container Apps log stream in the cloud. A ``run_id`` (and any
other bound context) is attached to every line automatically via
:mod:`structlog.contextvars`, so all logs for one reconciliation run can be
correlated.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog

_DEFAULT_LEVEL = logging.INFO


def _resolve_level(level: str) -> int:
    """Map a level name (e.g. ``"INFO"``) to its numeric value, defaulting to INFO."""
    mapping = logging.getLevelNamesMapping()
    return mapping.get(level.upper(), _DEFAULT_LEVEL)


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for JSON output. Safe to call more than once."""
    numeric_level = _resolve_level(level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger, optionally tagged with a component ``name``."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    if name is not None:
        return logger.bind(component=name)
    return logger


def new_run_id() -> str:
    """Generate a fresh UUID4 run identifier."""
    return str(uuid.uuid4())


def bind_run_id(run_id: str) -> None:
    """Bind ``run_id`` to the logging context for the current execution scope."""
    structlog.contextvars.bind_contextvars(run_id=run_id)


def clear_context() -> None:
    """Clear all bound context variables."""
    structlog.contextvars.clear_contextvars()


@contextmanager
def run_context(run_id: str | None = None, **extra: Any) -> Iterator[str]:
    """Bind ``run_id`` (and any extra context) for the duration of a ``with`` block.

    Yields the run id so callers can persist or return it. Previously-bound
    context is restored on exit.
    """
    resolved = run_id or new_run_id()
    tokens = structlog.contextvars.bind_contextvars(run_id=resolved, **extra)
    try:
        yield resolved
    finally:
        structlog.contextvars.reset_contextvars(**tokens)
