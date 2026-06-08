"""HTTP middleware: per-request id binding and request logging."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from reconcile.logging_setup import get_logger, new_run_id, run_context

_log = get_logger("api")


async def logging_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Bind a request id to the log context and log start/end of each request."""
    request_id = new_run_id()
    with run_context(request_id, path=request.url.path, method=request.method):
        _log.info("request_started")
        response = await call_next(request)
        _log.info("request_completed", status_code=response.status_code)
        response.headers["X-Request-ID"] = request_id
        return response


def register_middleware(app: FastAPI) -> None:
    """Attach middleware to the application."""
    app.middleware("http")(logging_middleware)
