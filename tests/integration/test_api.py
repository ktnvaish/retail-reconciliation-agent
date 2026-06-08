"""API tests using FastAPI's TestClient."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reconcile.app import create_app
from reconcile.config import AppSettings

pytestmark = pytest.mark.integration


@pytest.fixture
def client(settings: AppSettings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture
def keyed_client(make_settings: Callable[..., AppSettings]) -> TestClient:
    return TestClient(create_app(make_settings(demo_access_key="secret")))


def _files(samples_dir: Path) -> dict[str, tuple[str, bytes, str]]:
    return {
        "orders": (
            "orders_sample.csv",
            (samples_dir / "orders_sample.csv").read_bytes(),
            "text/csv",
        ),
        "settlements": (
            "settlements_sample.csv",
            (samples_dir / "settlements_sample.csv").read_bytes(),
            "text/csv",
        ),
    }


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_page(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Reconcile orders" in response.text


def test_demo_endpoint_runs(client: TestClient) -> None:
    response = client.post("/demo", data={"dry_run": "true"})
    assert response.status_code == 200
    assert "Reconciliation result" in response.text
    assert "/runs/" in response.text


def test_reconcile_with_uploads(client: TestClient, samples_dir: Path) -> None:
    response = client.post("/reconcile", files=_files(samples_dir), data={"dry_run": "true"})
    assert response.status_code == 200
    assert "Reconciliation result" in response.text


def test_reconcile_invalid_file_shows_errors(client: TestClient) -> None:
    bad = {
        "orders": ("orders.csv", b"order_id,order_date\nO1,2026-06-06\n", "text/csv"),
        "settlements": (
            "settlements.csv",
            b"settlement_id,settlement_date,payment_type,amount,source\nS1,2026-06-07,CARD,100.00,BANK\n",
            "text/csv",
        ),
    }
    response = client.post("/reconcile", files=bad, data={"dry_run": "true"})
    assert response.status_code == 400
    assert "missing required column" in response.text.lower()


def test_metrics_after_run(client: TestClient) -> None:
    client.post("/demo", data={"dry_run": "false"})
    response = client.get("/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["runs_total"] >= 1
    assert "circuit_breaker" in payload
    assert payload["notifications"]


def test_run_detail(client: TestClient) -> None:
    demo = client.post("/demo", data={"dry_run": "false"})
    match = re.search(r"/runs/([0-9a-f-]{36})", demo.text)
    assert match is not None
    run_id = match.group(1)

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["id"] == run_id
    assert payload["events"]
    assert payload["notifications"]


def test_run_detail_not_found(client: TestClient) -> None:
    response = client.get("/runs/does-not-exist")
    assert response.status_code == 404


def test_demo_key_required(keyed_client: TestClient, samples_dir: Path) -> None:
    response = keyed_client.post("/reconcile", files=_files(samples_dir), data={"dry_run": "true"})
    assert response.status_code == 401
