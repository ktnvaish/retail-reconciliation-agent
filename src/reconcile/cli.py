"""Command-line interface.

Commands:

* ``serve``   — run the FastAPI web app (honors ``$PORT``).
* ``run``     — reconcile two files and print a summary.
* ``demo``    — run the agent against the bundled sample data.
* ``init-db`` — create the database schema.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer
import uvicorn
from sqlalchemy.orm import sessionmaker

from reconcile.agent.service import ReconciliationAgent, RunOutcome, build_agent
from reconcile.config import AppSettings, NotifierName, get_settings, load_app_config
from reconcile.db import create_db_engine, init_db
from reconcile.logging_setup import configure_logging
from reconcile.parsers import read_orders, read_settlements

app = typer.Typer(help="ReconcileFlow Agent — agentic retail payment reconciliation.")

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"


def _wire(settings: AppSettings) -> ReconciliationAgent:
    configure_logging(settings.log_level)
    config = load_app_config(settings)
    engine = create_db_engine(settings)
    init_db(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return build_agent(settings, config, session_factory)


def _print_summary(outcome: RunOutcome, settings: AppSettings) -> None:
    typer.echo(f"run_id:        {outcome.run_id}")
    typer.echo(f"status:        {outcome.status}")
    typer.echo(f"matched:       {outcome.summary.get('matched', 0)}")
    typer.echo(f"exceptions:    {outcome.summary.get('exceptions_total', 0)}")
    typer.echo(f"by reason:     {outcome.summary.get('exceptions_by_reason', {})}")
    typer.echo(f"actions:       {outcome.summary.get('actions', {})}")
    typer.echo(f"notifications: {outcome.summary.get('notifications', {})}")
    typer.echo(f"fuzzy matched: {outcome.fuzzy_auto_applied}")
    if outcome.incident_id:
        typer.echo(f"incident:      {outcome.incident_id}")
    if settings.notifier == "mock":
        typer.echo(f"mock outbox:   {settings.mock_outbox_path}")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind address."),
    port: int | None = typer.Option(None, help="Port (defaults to $PORT / settings)."),
) -> None:
    """Run the web application with uvicorn."""
    settings = get_settings()
    uvicorn.run(
        "reconcile.app:create_app",
        factory=True,
        host=host,
        port=port or settings.port,
        log_config=None,
    )


@app.command()
def run(
    orders: Path = typer.Argument(..., exists=True, readable=True, help="Orders file."),
    settlements: Path = typer.Argument(..., exists=True, readable=True, help="Settlements file."),
    dry_run: bool = typer.Option(False, help="Compute and preview without sending."),
    as_of: str | None = typer.Option(None, help="Evaluation date (YYYY-MM-DD)."),
) -> None:
    """Reconcile two files and print a summary."""
    settings = get_settings()
    agent = _wire(settings)
    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    outcome = agent.run(
        orders=read_orders(orders),
        settlements=read_settlements(settlements),
        as_of_date=as_of_date,
        dry_run=dry_run,
    )
    _print_summary(outcome, settings)


@app.command()
def demo(
    notifier: str | None = typer.Option(None, help="Override notifier: mock | smtp | resend."),
    dry_run: bool = typer.Option(False, help="Compute and preview without sending."),
) -> None:
    """Run the agent against the bundled sample dataset."""
    settings = get_settings()
    if notifier is not None:
        settings = settings.model_copy(update={"notifier": _as_notifier(notifier)})
    agent = _wire(settings)
    outcome = agent.run(
        orders=read_orders(_SAMPLES_DIR / "orders_sample.csv"),
        settlements=read_settlements(_SAMPLES_DIR / "settlements_sample.csv"),
        as_of_date=date(2026, 6, 8),
        dry_run=dry_run,
    )
    _print_summary(outcome, settings)


@app.command("init-db")
def init_db_command() -> None:
    """Create the database schema."""
    settings = get_settings()
    engine = create_db_engine(settings)
    init_db(engine)
    typer.echo(f"Initialized database at {settings.database_url}")


def _as_notifier(value: str) -> NotifierName:
    if value not in ("mock", "smtp", "resend"):
        raise typer.BadParameter("notifier must be one of: mock, smtp, resend")
    return value  # type: ignore[return-value]


if __name__ == "__main__":
    app()
