"""Incident orchestration with durable administrator notification.

On every incident the service guarantees a durable record reaches the admin:

1. the incident is written to JSON + ``incidents.jsonl`` (by the store), and
2. a structured line is printed to **stderr**,

*before* a best-effort email is attempted. If email is the failing component,
steps 1-2 still ensure the admin is never silently unreachable.
"""

from __future__ import annotations

import json
import sys

from reconcile.incidents.models import FailureType, Incident
from reconcile.incidents.store import IncidentStore
from reconcile.logging_setup import get_logger
from reconcile.models.domain import RecipientRole
from reconcile.notifications.service import NotificationService

_log = get_logger("incident_service")


class IncidentService:
    """Creates incidents and notifies the admin through a durable channel."""

    def __init__(
        self,
        *,
        store: IncidentStore,
        admin_email: str,
        notification_service: NotificationService | None = None,
        best_effort_email: bool = True,
    ) -> None:
        self._store = store
        self._admin_email = admin_email
        self._notification_service = notification_service
        self._best_effort_email = best_effort_email

    def raise_incident(
        self,
        *,
        run_id: str,
        failure_type: FailureType,
        root_cause: str,
        order_id: str | None = None,
        remediation: str | None = None,
    ) -> Incident:
        """Persist an incident and notify the admin durably."""
        incident = self._store.create(
            run_id=run_id,
            failure_type=failure_type,
            root_cause=root_cause,
            order_id=order_id,
            remediation=remediation,
        )
        self._notify_admin(incident)
        return incident

    def _notify_admin(self, incident: Incident) -> None:
        # 1. Durable console record (independent of any email provider).
        print(json.dumps(incident.to_json_dict()), file=sys.stderr)

        # 2. Best-effort email (never allowed to break incident handling).
        if not (self._best_effort_email and self._notification_service and self._admin_email):
            return
        try:
            self._notification_service.dispatch(
                run_id=incident.run_id,
                mismatch_key=f"incident:{incident.incident_id}",
                recipient_role=RecipientRole.ADMIN,
                recipient_email=self._admin_email,
                subject=f"[{incident.severity.value}] Reconciliation incident {incident.incident_id}",
                body=_incident_email_body(incident),
            )
        except Exception as exc:
            _log.warning("admin_email_failed", incident_id=incident.incident_id, error=str(exc))


def _incident_email_body(incident: Incident) -> str:
    lines = [
        f"An unrecoverable failure occurred during reconciliation run {incident.run_id}.",
        "",
        f"Incident:    {incident.incident_id}",
        f"Severity:    {incident.severity.value}",
        f"Failure:     {incident.failure_type.value}",
        f"Root cause:  {incident.root_cause}",
    ]
    if incident.order_id:
        lines.append(f"Order:       {incident.order_id}")
    if incident.remediation_recommendation:
        lines.append(f"Remediation: {incident.remediation_recommendation}")
    return "\n".join(lines)
