"""Retry helpers built on tenacity.

A single generic ``call_with_retry`` is reused for both email sending and LLM
calls; callers pass the exception type(s) that should be retried so transient
failures back off exponentially while permanent ones fail fast.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from reconcile.notifications.base import TransientNotifyError

T = TypeVar("T")


def call_with_retry(
    func: Callable[[], T],
    *,
    attempts: int,
    min_seconds: float,
    max_seconds: float,
    retry_on: type[Exception] | tuple[type[Exception], ...] = TransientNotifyError,
) -> T:
    """Call ``func`` with exponential-backoff retries on ``retry_on`` exceptions.

    The final exception is re-raised once attempts are exhausted.
    """
    retryer = Retrying(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=min_seconds, max=max_seconds),
        retry=retry_if_exception_type(retry_on),
        reraise=True,
    )
    return retryer(func)
