"""Deterministic incident severity rules (never decided by the LLM)."""

from __future__ import annotations

from reconcile.incidents.models import FailureType
from reconcile.models.domain import IncidentSeverity

_SEVERITY_BY_TYPE: dict[FailureType, IncidentSeverity] = {
    FailureType.CONFIG_ERROR: IncidentSeverity.CRITICAL,
    FailureType.LLM_UNAVAILABLE: IncidentSeverity.HIGH,
    FailureType.EMAIL_FAILED: IncidentSeverity.HIGH,
    FailureType.PLANNER_ERROR: IncidentSeverity.HIGH,
    FailureType.INVALID_INPUT: IncidentSeverity.MEDIUM,
    FailureType.UNSUPPORTED_PAYMENT_TYPE: IncidentSeverity.LOW,
    FailureType.UNKNOWN: IncidentSeverity.HIGH,
}


def determine_severity(failure_type: FailureType) -> IncidentSeverity:
    """Map a failure type to a severity using fixed rules."""
    return _SEVERITY_BY_TYPE.get(failure_type, IncidentSeverity.HIGH)
