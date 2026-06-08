"""Circuit breaker around the notification provider.

Wraps notifier calls with a :mod:`pybreaker` circuit breaker so a failing email
provider is given a rest instead of being hammered. State transitions are logged
as structured events and the breaker instance exposes its state for ``/metrics``.
"""

from __future__ import annotations

from typing import Any

import pybreaker

from reconcile.logging_setup import get_logger

_log = get_logger("circuit_breaker")


class _LoggingListener(pybreaker.CircuitBreakerListener):
    """Emit a structured log line whenever the breaker changes state."""

    def state_change(
        self,
        cb: pybreaker.CircuitBreaker,
        old_state: Any,
        new_state: Any,
    ) -> None:
        _log.warning(
            "circuit_breaker_state_change",
            breaker=cb.name,
            old_state=getattr(old_state, "name", str(old_state)),
            new_state=getattr(new_state, "name", str(new_state)),
        )


def build_circuit_breaker(
    *,
    name: str,
    fail_max: int,
    reset_timeout: int,
) -> pybreaker.CircuitBreaker:
    """Create a circuit breaker that opens after ``fail_max`` consecutive failures."""
    return pybreaker.CircuitBreaker(
        fail_max=fail_max,
        reset_timeout=reset_timeout,
        name=name,
        listeners=[_LoggingListener()],
    )
