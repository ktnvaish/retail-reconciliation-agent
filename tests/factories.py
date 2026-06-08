"""Builder helpers for tests (not collected by pytest)."""

from __future__ import annotations

from datetime import date
from typing import Any

from reconcile.models.domain import (
    Obligation,
    Order,
    OrderStatus,
    PaymentGateway,
    PaymentType,
    Settlement,
    SettlementSource,
)

DEFAULT_DATE = date(2026, 6, 6)
AS_OF = date(2026, 6, 8)


def make_order(**overrides: Any) -> Order:
    base: dict[str, Any] = {
        "order_id": "O1",
        "order_date": DEFAULT_DATE,
        "store_id": "S1",
        "amount": "500.00",
        "payment_type": PaymentType.CASH,
        "payment_amount": "500.00",
        "status": OrderStatus.PLACED,
    }
    base.update(overrides)
    return Order.model_validate(base)


def make_online_order(**overrides: Any) -> Order:
    base: dict[str, Any] = {
        "order_id": "O1",
        "order_date": DEFAULT_DATE,
        "store_id": "S1",
        "amount": "1000.00",
        "payment_type": PaymentType.CARD,
        "payment_amount": "1000.00",
        "payment_gateway": PaymentGateway.RAZORPAY,
        "gateway_txn_id": "TXN1",
        "status": OrderStatus.PLACED,
    }
    base.update(overrides)
    return Order.model_validate(base)


def make_obligation(**overrides: Any) -> Obligation:
    base: dict[str, Any] = {
        "obligation_id": "OB1",
        "order_id": "O1",
        "order_date": DEFAULT_DATE,
        "store_id": "S1",
        "payment_type": PaymentType.CARD,
        "expected_amount": "1000.00",
        "payment_gateway": PaymentGateway.RAZORPAY,
        "gateway_txn_id": "TXN1",
    }
    base.update(overrides)
    return Obligation.model_validate(base)


def make_settlement(**overrides: Any) -> Settlement:
    base: dict[str, Any] = {
        "settlement_id": "ST1",
        "settlement_date": date(2026, 6, 7),
        "payment_type": PaymentType.CARD,
        "amount": "1000.00",
        "net_amount": "1000.00",
        "source": SettlementSource.RAZORPAY,
        "gateway_txn_id": "TXN1",
    }
    base.update(overrides)
    return Settlement.model_validate(base)
