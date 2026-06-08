"""Durable incident persistence.

Each incident is written as an individual ``<incident_id>.json`` file *and*
appended to an ``incidents.jsonl`` stream in the same directory. The JSONL stream
is the durable record that the admin notifier relies on even when email is the
failing component.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from reconcile.incidents.models import FailureType, Incident
from reconcile.incidents.severity import determine_severity
from reconcile.logging_setup import get_logger

_log = get_logger("incident_store")


class IncidentStore:
    """Writes incidents to per-incident JSON files and an append-only JSONL log."""

    def __init__(self, incidents_dir: Path) -> None:
        self._dir = incidents_dir

    @property
    def jsonl_path(self) -> Path:
        return self._dir / "incidents.jsonl"

    def create(
        self,
        *,
        run_id: str,
        failure_type: FailureType,
        root_cause: str,
        order_id: str | None = None,
        remediation: str | None = None,
    ) -> Incident:
        """Create, persist, and return a new incident."""
        incident = Incident(
            incident_id=f"inc-{uuid.uuid4().hex[:12]}",
            run_id=run_id,
            severity=determine_severity(failure_type),
            failure_type=failure_type,
            root_cause=root_cause,
            order_id=order_id,
            remediation_recommendation=remediation,
        )
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = incident.to_json_dict()

        (self._dir / f"{incident.incident_id}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")

        _log.error(
            "incident_created",
            incident_id=incident.incident_id,
            run_id=run_id,
            severity=incident.severity.value,
            failure_type=failure_type.value,
        )
        return incident

    def count_by_status(self) -> dict[str, int]:
        """Tally incidents in the JSONL stream by status (for ``/metrics``)."""
        counts: dict[str, int] = {}
        if not self.jsonl_path.exists():
            return counts
        for line in self.jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            status = json.loads(line).get("status", "OPEN")
            counts[status] = counts.get(status, 0) + 1
        return counts
