"""Structured schemas for LLM inputs and outputs.

Keeping these as small Pydantic models means the LLM's responses are validated
before use (the agent never trusts free-form text), and the same models drive
both the real Groq client and the deterministic mock.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from reconcile.models.domain import PlannerAction


class Severity(StrEnum):
    """How urgently a human should look at an exception."""

    ROUTINE = "ROUTINE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    HIGH_VALUE = "HIGH_VALUE"


class ExceptionDecision(BaseModel):
    """The LLM's per-exception decision: how severe, and what to do next."""

    model_config = ConfigDict(extra="forbid")

    severity: Severity
    action: PlannerAction
    rationale: str = Field(min_length=1, max_length=500)


class FuzzyPairing(BaseModel):
    """A proposed pairing between an unmatched obligation and settlement.

    The ids are nullable because real models sometimes emit placeholder rows for
    orders they could not pair (``settlement_id: null``); such rows are filtered
    out during application rather than rejected, so a single odd row never fails
    the whole structured-output call.
    """

    model_config = ConfigDict(extra="forbid")

    order_id: str | None = None
    settlement_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=300)


class FuzzyProposal(BaseModel):
    """A batch of fuzzy pairing proposals."""

    model_config = ConfigDict(extra="forbid")

    pairings: list[FuzzyPairing] = Field(default_factory=list)


class EmailDraft(BaseModel):
    """An LLM-drafted (or template-drafted) notification email."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)


class EmailMessageView(BaseModel):
    """A dispatched (or previewed) email, for display in the UI / run outcome."""

    model_config = ConfigDict(extra="forbid")

    recipient_role: str
    recipient_email: str
    subject: str
    body: str
    status: str
    reason: str | None = None
    mismatch_key: str


class ExceptionView(BaseModel):
    """A flattened, serializable view of an exception and its decision."""

    model_config = ConfigDict(extra="forbid")

    reason: str
    status: str
    order_id: str | None = None
    settlement_id: str | None = None
    payment_type: str | None = None
    expected_amount: str | None = None
    actual_amount: str | None = None
    sla_status: str
    severity: str
    action: str
    rationale: str
