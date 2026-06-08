"""API tests using FastAPI's TestClient."""

from __future__ import annotations

import re
import time
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


def _run_id_from(text: str) -> str:
    """Extract the run id rendered on the progress page."""
    match = re.search(r'data-run-id="([0-9a-f-]{36})"', text)
    assert match is not None, "progress page did not contain a run id"
    return match.group(1)


def _wait_until_done(client: TestClient, run_id: str, *, timeout_s: float = 30.0) -> dict:
    """Poll the progress endpoint until the run completes (or time out)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        response = client.get(f"/runs/{run_id}/progress")
        assert response.status_code == 200
        payload = response.json()
        if payload["done"]:
            return payload
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not finish within {timeout_s}s")


def _run_demo_to_completion(client: TestClient, *, dry_run: bool = True) -> str:
    """Trigger a demo run and block until it finishes; return the run id."""
    response = client.post("/demo", data={"dry_run": str(dry_run).lower()})
    assert response.status_code == 200
    assert "Reconciling" in response.text
    run_id = _run_id_from(response.text)
    _wait_until_done(client, run_id)
    return run_id


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_page(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Reconcile orders" in response.text


def test_demo_endpoint_runs(client: TestClient) -> None:
    run_id = _run_demo_to_completion(client, dry_run=True)
    results = client.get(f"/results/{run_id}")
    assert results.status_code == 200
    assert "Reconciliation result" in results.text


def test_reconcile_with_uploads(client: TestClient, samples_dir: Path) -> None:
    response = client.post("/reconcile", files=_files(samples_dir), data={"dry_run": "true"})
    assert response.status_code == 200
    assert "Reconciling" in response.text
    run_id = _run_id_from(response.text)
    _wait_until_done(client, run_id)
    results = client.get(f"/results/{run_id}")
    assert results.status_code == 200
    assert "Reconciliation result" in results.text


def test_reconcile_invalid_file_shows_errors(client: TestClient) -> None:
    bad = {
        "orders": ("orders.csv", b"order_id,order_date\nO1,2026-06-06\n", "text/csv"),
        "settlements": (
            "settlements.csv",
            b"settlement_id,settlement_date,payment_type,amount,source\nS1,2026-06-07,CARD,100.00,BANK\n",
            "text/csv",
        ),
    }
    # Validation is still synchronous, so the error shows immediately.
    response = client.post("/reconcile", files=bad, data={"dry_run": "true"})
    assert response.status_code == 400
    assert "missing required column" in response.text.lower()


def test_metrics_after_run(client: TestClient) -> None:
    _run_demo_to_completion(client, dry_run=False)
    response = client.get("/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["runs_total"] >= 1
    assert "circuit_breaker" in payload
    assert payload["notifications"]


def test_run_detail(client: TestClient) -> None:
    run_id = _run_demo_to_completion(client, dry_run=False)
    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["id"] == run_id
    assert payload["events"]
    assert payload["notifications"]


def test_progress_then_results(client: TestClient) -> None:
    response = client.post("/demo", data={"dry_run": "true"})
    run_id = _run_id_from(response.text)
    final = _wait_until_done(client, run_id)
    assert final["status"] == "completed"
    assert final["percent"] == 100
    assert final["redirect"] == f"/results/{run_id}"


def test_progress_unknown_run_404(client: TestClient) -> None:
    response = client.get("/runs/does-not-exist/progress")
    assert response.status_code == 404


def test_run_detail_not_found(client: TestClient) -> None:
    response = client.get("/runs/does-not-exist")
    assert response.status_code == 404


def test_demo_key_required(keyed_client: TestClient, samples_dir: Path) -> None:
    response = keyed_client.post("/reconcile", files=_files(samples_dir), data={"dry_run": "true"})
    assert response.status_code == 401
