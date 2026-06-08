"""Tests for incident severity, persistence, and durable admin notification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reconcile.incidents.models import FailureType
from reconcile.incidents.service import IncidentService
from reconcile.incidents.severity import determine_severity
from reconcile.incidents.store import IncidentStore
from reconcile.models.domain import IncidentSeverity, IncidentStatus

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("failure_type", "expected"),
    [
        (FailureType.CONFIG_ERROR, IncidentSeverity.CRITICAL),
        (FailureType.LLM_UNAVAILABLE, IncidentSeverity.HIGH),
        (FailureType.EMAIL_FAILED, IncidentSeverity.HIGH),
        (FailureType.INVALID_INPUT, IncidentSeverity.MEDIUM),
        (FailureType.UNSUPPORTED_PAYMENT_TYPE, IncidentSeverity.LOW),
    ],
)
def test_determine_severity(failure_type: FailureType, expected: IncidentSeverity) -> None:
    assert determine_severity(failure_type) is expected


def test_store_writes_json_and_jsonl(tmp_path: Path) -> None:
    store = IncidentStore(tmp_path)
    incident = store.create(
        run_id="run-1",
        failure_type=FailureType.INVALID_INPUT,
        root_cause="missing column: order_id",
    )

    json_file = tmp_path / f"{incident.incident_id}.json"
    assert json_file.exists()
    payload = json.loads(json_file.read_text(encoding="utf-8"))
    assert payload["failure_type"] == "INVALID_INPUT"
    assert payload["severity"] == "MEDIUM"
    assert payload["status"] == IncidentStatus.OPEN.value

    lines = store.jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_store_count_by_status(tmp_path: Path) -> None:
    store = IncidentStore(tmp_path)
    store.create(run_id="r", failure_type=FailureType.EMAIL_FAILED, root_cause="x")
    store.create(run_id="r", failure_type=FailureType.LLM_UNAVAILABLE, root_cause="y")
    assert store.count_by_status() == {"OPEN": 2}


class _ExplodingNotificationService:
    """Stands in for a notification service whose email path is broken."""

    def dispatch(self, **_kwargs: object) -> None:
        raise RuntimeError("email subsystem is down")


def test_admin_notified_durably_even_when_email_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = IncidentStore(tmp_path)
    service = IncidentService(
        store=store,
        admin_email="admin@demo.local",
        notification_service=_ExplodingNotificationService(),  # type: ignore[arg-type]
    )

    incident = service.raise_incident(
        run_id="run-1",
        failure_type=FailureType.EMAIL_FAILED,
        root_cause="circuit open after retries",
    )

    # Durable record exists despite the email failure.
    assert store.jsonl_path.exists()
    assert len(store.jsonl_path.read_text(encoding="utf-8").splitlines()) == 1

    # And the admin received a durable stderr line containing the incident id.
    stderr = capsys.readouterr().err
    assert incident.incident_id in stderr
