"""Pydantic domain models and enumerations.

This module is the single source of truth for the system's value objects. It has
no dependency on configuration, persistence, or the agent, so every other layer
can import it freely without risk of circular imports.

Money is represented with :class:`~decimal.Decimal` (quantized to paise) so that
reconciliation arithmetic is exact — never floating-point.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

# --------------------------------------------------------------------------- #
# Money type
# --------------------------------------------------------------------------- #

_PAISE = Decimal("0.01")


def _to_money(value: object) -> Decimal:
    """Coerce an incoming value to a 2-decimal-place :class:`Decimal`.

    Strings and ints/floats (as produced by spreadsheet parsing) are accepted;
    floats are routed through ``str`` first to avoid binary-float artifacts.
    """
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, str):
        amount = Decimal(value.strip() or "0")
    else:
        amount = Decimal(str(value))
    return amount.quantize(_PAISE, rounding=ROUND_HALF_UP)


Money = Annotated[Decimal, BeforeValidator(_to_money), Field(ge=Decimal("0"))]
"""A non-negative monetary amount, quantized to two decimal places (paise)."""


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class PaymentType(StrEnum):
    """How a customer paid for (part of) an order."""

    CASH = "CASH"
    UPI = "UPI"
    CARD = "CARD"
    NETBANKING = "NETBANKING"
    WALLET = "WALLET"

    @property
    def is_online(self) -> bool:
        """True for any non-cash payment type (settled via a gateway/bank)."""
        return self is not PaymentType.CASH


class PaymentGateway(StrEnum):
    """Supported online payment gateways."""

    RAZORPAY = "RAZORPAY"
    PAYU = "PAYU"
    CASHFREE = "CASHFREE"


class OrderStatus(StrEnum):
    """Lifecycle status of an order row. Only ``PLACED`` rows are reconciled."""

    PLACED = "PLACED"
    CANCELLED = "CANCELLED"


class SettlementSource(StrEnum):
    """Origin of a settlement entry."""

    BANK = "BANK"
    RAZORPAY = "RAZORPAY"
    PAYU = "PAYU"
    CASHFREE = "CASHFREE"


class RecipientRole(StrEnum):
    """A stakeholder role that can receive a notification."""

    STORE_MANAGER = "STORE_MANAGER"
    PAYMENT_GATEWAY = "PAYMENT_GATEWAY"
    BANK = "BANK"
    ADMIN = "ADMIN"


class ObligationStatus(StrEnum):
    """Deterministic outcome of reconciling one obligation against settlements."""

    MATCHED = "MATCHED"
    PARTIALLY_MATCHED = "PARTIALLY_MATCHED"
    EXCESS = "EXCESS"
    DUPLICATE = "DUPLICATE"
    UNMATCHED = "UNMATCHED"


class ExceptionReason(StrEnum):
    """Why a non-matched obligation (or stray settlement) needs attention."""

    CASH_MISSING = "CASH_MISSING"
    ONLINE_MISSING = "ONLINE_MISSING"
    LATE_SETTLEMENT = "LATE_SETTLEMENT"
    AMOUNT_SHORT = "AMOUNT_SHORT"
    AMOUNT_EXCESS = "AMOUNT_EXCESS"
    DUPLICATE_SETTLEMENT = "DUPLICATE_SETTLEMENT"
    UNMATCHED_SETTLEMENT = "UNMATCHED_SETTLEMENT"
    ORDER_SUM_MISMATCH = "ORDER_SUM_MISMATCH"
    FUZZY_MATCH_REVIEW = "FUZZY_MATCH_REVIEW"


class SlaStatus(StrEnum):
    """Whether an obligation is within its settlement SLA window."""

    WITHIN_SLA = "WITHIN_SLA"
    BREACHED = "BREACHED"
    NA = "NA"


class PlannerAction(StrEnum):
    """The controlled allow-list of actions the planner may choose per exception."""

    WAIT = "WAIT"
    EMAIL_STORE_MANAGER = "EMAIL_STORE_MANAGER"
    EMAIL_PG = "EMAIL_PG"
    EMAIL_BANK = "EMAIL_BANK"
    ESCALATE = "ESCALATE"
    REQUEST_RECHECK = "REQUEST_RECHECK"


class ExceptionLifecycleStatus(StrEnum):
    """Lifecycle of an exception tracked across runs in the exception log."""

    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    AWAITING_RECHECK = "AWAITING_RECHECK"


class NotificationChannel(StrEnum):
    """Delivery channel for a notification (email only, for now)."""

    EMAIL = "EMAIL"


class NotificationStatus(StrEnum):
    """Outcome of a single notification attempt."""

    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class IncidentSeverity(StrEnum):
    """Severity of an unrecoverable system failure (assigned deterministically)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(StrEnum):
    """Lifecycle of an incident record."""

    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"


# Sentinel used in mismatch keys when an exception is not tied to a payment type
# (e.g. an order-level sum mismatch).
PAYMENT_TYPE_WILDCARD = "*"


# --------------------------------------------------------------------------- #
# Core value objects
# --------------------------------------------------------------------------- #


class Order(BaseModel):
    """A single validated row from the orders file.

    One order (``order_id``) may span multiple rows — one per payment obligation
    (e.g. part CARD + part CASH). ``amount`` is the order gross total and is
    identical on every row of the same order; ``payment_amount`` is *this* row's
    obligation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    order_id: str
    order_date: date
    store_id: str
    amount: Money
    payment_type: PaymentType
    payment_amount: Money
    payment_gateway: PaymentGateway | None = None
    gateway_txn_id: str | None = None
    responsible_party: RecipientRole | None = None
    status: OrderStatus = OrderStatus.PLACED
    customer_name: str | None = None
    customer_email: str | None = None

    @model_validator(mode="after")
    def _check_payment_fields(self) -> Order:
        """Online (non-cash) obligations must carry a gateway and transaction id."""
        if self.payment_type.is_online:
            if not self.gateway_txn_id:
                raise ValueError("gateway_txn_id is required for non-cash payments")
            if self.payment_gateway is None:
                raise ValueError("payment_gateway is required for non-cash payments")
        return self


class Settlement(BaseModel):
    """A single validated row from the settlements file (money actually received)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    settlement_id: str
    settlement_date: date
    payment_type: PaymentType
    amount: Money
    net_amount: Money
    source: SettlementSource
    fee: Money = Decimal("0.00")
    order_id: str | None = None
    gateway_txn_id: str | None = None
    reference_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _default_net_amount(cls, data: object) -> object:
        """Default ``net_amount`` to ``amount - fee`` when the column is blank."""
        if isinstance(data, dict) and not data.get("net_amount"):
            amount = data.get("amount")
            if amount not in (None, ""):
                fee = data.get("fee") or "0"
                data = {**data, "net_amount": str(Decimal(str(amount)) - Decimal(str(fee)))}
        return data


class Obligation(BaseModel):
    """A reconciliation unit derived from a single ``PLACED`` order row.

    ``obligation_id`` is unique within a run: the gateway transaction id for
    online payments, or a deterministic ``order_id:payment_type:seq`` key for
    cash (which has no transaction id).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    obligation_id: str
    order_id: str
    order_date: date
    store_id: str
    payment_type: PaymentType
    expected_amount: Money
    payment_gateway: PaymentGateway | None = None
    gateway_txn_id: str | None = None
    responsible_party: RecipientRole | None = None
    customer_name: str | None = None
    customer_email: str | None = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def make_obligation_id(
    order_id: str, payment_type: PaymentType, gateway_txn_id: str | None, seq: int
) -> str:
    """Build a run-unique obligation id.

    Online obligations key on their (unique) gateway transaction id; cash falls
    back to a deterministic ``order_id:payment_type:seq`` composite.
    """
    if gateway_txn_id:
        return gateway_txn_id
    return f"{order_id}:{payment_type.value}:{seq}"


def make_mismatch_key(
    reason: ExceptionReason,
    order_id: str | None,
    settlement_id: str | None,
    payment_type: PaymentType | None,
    recipient_role: RecipientRole,
) -> str:
    """Compute the stable idempotency key for a routed exception.

    The key is ``sha1(reason|order_id|settlement_id|payment_type|recipient_role)``.
    It is deterministic across runs, so re-processing the same inputs yields the
    same key and the notification log can enforce "do not double-notify".
    """
    payment = payment_type.value if payment_type is not None else PAYMENT_TYPE_WILDCARD
    raw = "|".join(
        [
            reason.value,
            order_id or "",
            settlement_id or "",
            payment,
            recipient_role.value,
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()
