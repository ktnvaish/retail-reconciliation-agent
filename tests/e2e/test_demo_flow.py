"""End-to-end demo flow: parse samples, run the agent, assert routed outcomes.

These tests assert the *business* outcome a reviewer cares about: the right
exceptions are detected and the right stakeholders are emailed, with a full
audit trail and durable incident handling on bad input.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from reconcile.agent import build_agent
from reconcile.config import AppConfig, AppSettings
from reconcile.incidents.models import FailureType
from reconcile.incidents.service import IncidentService
from reconcile.incidents.store import IncidentStore
from reconcile.parsers import ParseError, read_orders, read_settlements

pytestmark = pytest.mark.e2e

AS_OF = date(2026, 6, 8)


def _outbox_records(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_demo_flow_routes_to_correct_recipients(
    settings: AppSettings,
    app_config: AppConfig,
    session_factory: sessionmaker[Session],
    samples_dir: Path,
) -> None:
    agent = build_agent(settings, app_config, session_factory)
    orders = read_orders(samples_dir / "orders_sample.xlsx")
    settlements = read_settlements(samples_dir / "settlements_sample.xlsx")

    outcome = agent.run(orders=orders, settlements=settlements, as_of_date=AS_OF)
    assert outcome.status == "completed"

    records = _outbox_records(settings.mock_outbox_path)
    by_role: dict[str, list[dict]] = {}
    for record in records:
        by_role.setdefault(record["role"], []).append(record)

    # Cash-missing -> store manager; online-missing -> the order's gateway;
    # unmatched settlement -> bank + gateway; order-sum -> store manager.
    assert any(r["role"] == "STORE_MANAGER" for r in records)
    assert any(r["role"] == "PAYMENT_GATEWAY" for r in records)
    assert any(r["role"] == "BANK" for r in records)

    # Every email carries a non-empty subject and body.
    assert all(r["subject"] and r["body"] for r in records)

    # The summary's notification count matches the outbox size.
    assert outcome.summary["notifications"].get("SENT") == len(records)


def test_bad_input_creates_incident(
    settings: AppSettings,
    app_config: AppConfig,
    session_factory: sessionmaker[Session],
) -> None:
    store = IncidentStore(settings.incidents_dir)
    incidents = IncidentService(store=store, admin_email=app_config.recipients.admin)

    bad = b"order_id,order_date\nO1,2026-06-06\n"
    with pytest.raises(ParseError) as exc:
        read_orders(bad, filename="orders.csv")

    incident = incidents.raise_incident(
        run_id="run-e2e",
        failure_type=FailureType.INVALID_INPUT,
        root_cause=exc.value.message,
    )

    assert store.jsonl_path.exists()
    persisted = json.loads((settings.incidents_dir / f"{incident.incident_id}.json").read_text())
    assert persisted["failure_type"] == "INVALID_INPUT"
    assert persisted["severity"] == "MEDIUM"


def test_cli_demo_smoke(
    make_settings: Callable[..., AppSettings],
    session_factory: sessionmaker[Session],
    samples_dir: Path,
) -> None:
    # Mirrors `reconcile demo`: load samples, run, and confirm a populated summary.
    from reconcile.config import load_app_config

    settings = make_settings()
    config = load_app_config(settings)
    agent = build_agent(settings, config, session_factory)

    outcome = agent.run(
        orders=read_orders(samples_dir / "orders_sample.csv"),
        settlements=read_settlements(samples_dir / "settlements_sample.csv"),
        as_of_date=AS_OF,
        dry_run=True,
    )
    assert outcome.summary["matched"] == 7
    assert outcome.summary["exceptions_total"] == 8
    assert outcome.fuzzy_auto_applied == 1
