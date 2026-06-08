"""Incident data model and failure taxonomy.

An *incident* is an unrecoverable **system** failure (distinct from a planner
``ESCALATE``, which routes a valid business exception to a human).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from reconcile.models.domain import IncidentSeverity, IncidentStatus


class FailureType(StrEnum):
    """Categories of unrecoverable failure."""

    INVALID_INPUT = "INVALID_INPUT"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    EMAIL_FAILED = "EMAIL_FAILED"
    PLANNER_ERROR = "PLANNER_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"
    UNSUPPORTED_PAYMENT_TYPE = "UNSUPPORTED_PAYMENT_TYPE"
    UNKNOWN = "UNKNOWN"


class Incident(BaseModel):
    """A recorded unrecoverable failure."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    run_id: str
    severity: IncidentSeverity
    status: IncidentStatus = IncidentStatus.OPEN
    failure_type: FailureType
    root_cause: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    remediation_recommendation: str | None = None
    order_id: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        """A JSON-serializable representation (enums as values, ISO timestamps)."""
        return self.model_dump(mode="json")
