"""HTTP routes for the reconciliation web app."""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse

from reconcile.agent.service import RunOutcome
from reconcile.api.metrics import build_metrics_snapshot
from reconcile.api.progress import compute_progress
from reconcile.audit.idempotency import compute_input_hash
from reconcile.audit.repository import AuditRepository
from reconcile.incidents.models import FailureType
from reconcile.logging_setup import get_logger, new_run_id
from reconcile.models.domain import Order, Settlement
from reconcile.parsers import ParseError, read_orders, read_settlements

if TYPE_CHECKING:
    from reconcile.app import AppContext

_log = get_logger("api.routes")
_SAMPLES_DIR = Path(__file__).resolve().parents[3] / "data" / "samples"
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB per file


def _context(request: Request) -> AppContext:
    context: AppContext = request.app.state.context
    return context


def _check_demo_key(context: AppContext, request: Request, form_key: str) -> None:
    required = context.settings.demo_access_key
    if not required:
        return
    provided = request.headers.get("X-Demo-Key") or form_key
    if provided != required:
        raise HTTPException(status_code=401, detail="Invalid or missing demo access key.")


def _check_size(*blobs: bytes) -> None:
    for blob in blobs:
        if len(blob) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Uploaded file exceeds the 5 MB limit.")


def _start_background_run(
    context: AppContext,
    run_id: str,
    *,
    orders: list[Order],
    settlements: list[Settlement],
    as_of_date: date,
    dry_run: bool,
    demo: bool,
    input_hash: str | None = None,
) -> None:
    """Register and launch a reconciliation run on a background daemon thread.

    Parsing/validation has already happened synchronously by this point, so the
    background work is purely the (potentially slow) agent pipeline.
    """
    context.run_registry.start(run_id, demo=demo)

    def _worker() -> None:
        try:
            outcome = context.agent.run(
                orders=orders,
                settlements=settlements,
                run_id=run_id,
                as_of_date=as_of_date,
                input_hash=input_hash,
                dry_run=dry_run,
            )
            context.run_registry.set_outcome(run_id, outcome)
        except Exception as exc:  # defensive: surface unexpected failures to the UI
            _log.error("background_run_failed", run_id=run_id, error=str(exc))
            context.run_registry.set_error(run_id, str(exc))

    threading.Thread(target=_worker, name=f"run-{run_id[:8]}", daemon=True).start()


def register_routes(app: FastAPI) -> None:
    """Register all HTTP routes on the application."""

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        context = _context(request)
        return context.templates.TemplateResponse(
            request,
            "upload.html",
            {"demo_key_required": bool(context.settings.demo_access_key)},
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics(request: Request) -> dict[str, Any]:
        return build_metrics_snapshot(_context(request))

    @app.post("/reconcile", response_class=HTMLResponse)
    async def reconcile_endpoint(
        request: Request,
        orders: UploadFile = File(...),
        settlements: UploadFile = File(...),
        dry_run: bool = Form(False),
        demo_key: str = Form(""),
    ) -> HTMLResponse:
        context = _context(request)
        _check_demo_key(context, request, demo_key)

        orders_bytes = await orders.read()
        settlements_bytes = await settlements.read()
        _check_size(orders_bytes, settlements_bytes)

        try:
            parsed_orders = read_orders(orders_bytes, filename=orders.filename)
            parsed_settlements = read_settlements(settlements_bytes, filename=settlements.filename)
        except ParseError as exc:
            incident = context.deps.incidents.raise_incident(
                run_id=new_run_id(),
                failure_type=FailureType.INVALID_INPUT,
                root_cause=exc.message,
                remediation="Fix the highlighted rows and re-upload.",
            )
            return context.templates.TemplateResponse(
                request,
                "error.html",
                {"message": exc.message, "errors": exc.errors, "incident_id": incident.incident_id},
                status_code=400,
            )

        run_id = new_run_id()
        _start_background_run(
            context,
            run_id,
            orders=parsed_orders,
            settlements=parsed_settlements,
            as_of_date=date.today(),
            dry_run=dry_run,
            demo=False,
            input_hash=compute_input_hash(orders_bytes, settlements_bytes),
        )
        return context.templates.TemplateResponse(
            request, "progress.html", {"run_id": run_id, "demo": False}
        )

    @app.post("/demo", response_class=HTMLResponse)
    async def demo_endpoint(request: Request, dry_run: bool = Form(False)) -> HTMLResponse:
        context = _context(request)
        parsed_orders = read_orders(_SAMPLES_DIR / "orders_sample.csv")
        parsed_settlements = read_settlements(_SAMPLES_DIR / "settlements_sample.csv")

        run_id = new_run_id()
        _start_background_run(
            context,
            run_id,
            orders=parsed_orders,
            settlements=parsed_settlements,
            as_of_date=date(2026, 6, 8),
            dry_run=dry_run,
            demo=True,
        )
        return context.templates.TemplateResponse(
            request, "progress.html", {"run_id": run_id, "demo": True}
        )

    @app.get("/runs/{run_id}/progress")
    async def run_progress(request: Request, run_id: str) -> dict[str, Any]:
        info = compute_progress(_context(request), run_id)
        if info is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return info

    @app.get("/results/{run_id}", response_class=HTMLResponse)
    async def results_page(request: Request, run_id: str) -> HTMLResponse:
        context = _context(request)
        record = context.run_registry.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        if record.state == "pending":
            # Not finished yet — keep showing progress (it will redirect on done).
            return context.templates.TemplateResponse(
                request, "progress.html", {"run_id": run_id, "demo": record.demo}
            )
        if record.state == "error" or record.outcome is None:
            return context.templates.TemplateResponse(
                request,
                "error.html",
                {"message": record.error or "The run failed unexpectedly.", "errors": []},
                status_code=500,
            )
        outcome: RunOutcome = record.outcome
        return context.templates.TemplateResponse(
            request, "results.html", {"outcome": outcome, "demo": record.demo}
        )

    @app.get("/runs/{run_id}")
    async def run_detail(request: Request, run_id: str) -> dict[str, Any]:
        context = _context(request)
        with context.session_factory() as session:
            repo = AuditRepository(session)
            run = repo.get_run(run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="Run not found.")
            events = repo.list_events(run_id)
            notifications = repo.list_notifications(run_id)
            return {
                "run": {
                    "id": run.id,
                    "status": run.status,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "orders_count": run.orders_count,
                    "settlements_count": run.settlements_count,
                    "summary": run.summary_json,
                },
                "events": [
                    {
                        "ts": event.ts.isoformat() if event.ts else None,
                        "event_type": event.event_type,
                        "order_id": event.order_id,
                        "action": event.action,
                        "reason": event.reason,
                        "status": event.status,
                        "details": event.details,
                    }
                    for event in events
                ],
                "notifications": [
                    {
                        "mismatch_key": notif.mismatch_key,
                        "recipient_role": notif.recipient_role,
                        "recipient_email": notif.recipient_email,
                        "status": notif.status,
                        "error": notif.error,
                        "sent_at": notif.sent_at.isoformat() if notif.sent_at else None,
                    }
                    for notif in notifications
                ],
            }
