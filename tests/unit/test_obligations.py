"""Tests for obligation building and order-sum validation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from reconcile.models.domain import ExceptionReason, ObligationStatus, PaymentType
from reconcile.reconciliation import build_obligations
from tests.factories import make_online_order, make_order

pytestmark = pytest.mark.unit

TOLERANCE = Decimal("1.00")


def test_placed_rows_become_obligations() -> None:
    orders = [
        make_order(
            order_id="O1", payment_type=PaymentType.CASH, amount="500.00", payment_amount="500.00"
        ),
        make_online_order(
            order_id="O2", amount="1000.00", payment_amount="1000.00", gateway_txn_id="TXN2"
        ),
    ]
    result = build_obligations(orders, amount_tolerance=TOLERANCE)
    assert len(result.obligations) == 2
    assert not result.order_sum_exceptions


def test_cancelled_rows_are_skipped() -> None:
    orders = [make_order(status="CANCELLED")]
    result = build_obligations(orders, amount_tolerance=TOLERANCE)
    assert result.obligations == []


def test_online_obligation_id_is_txn_id() -> None:
    orders = [make_online_order(gateway_txn_id="TXN-XYZ")]
    result = build_obligations(orders, amount_tolerance=TOLERANCE)
    assert result.obligations[0].obligation_id == "TXN-XYZ"


def test_cash_obligation_id_is_composite() -> None:
    orders = [make_order(order_id="O9", payment_type=PaymentType.CASH)]
    result = build_obligations(orders, amount_tolerance=TOLERANCE)
    assert result.obligations[0].obligation_id == "O9:CASH:0"


def test_split_payment_sum_ok() -> None:
    orders = [
        make_online_order(
            order_id="O1", amount="1000.00", payment_amount="700.00", gateway_txn_id="T1"
        ),
        make_order(
            order_id="O1", amount="1000.00", payment_type=PaymentType.CASH, payment_amount="300.00"
        ),
    ]
    result = build_obligations(orders, amount_tolerance=TOLERANCE)
    assert len(result.obligations) == 2
    assert not result.order_sum_exceptions


def test_split_payment_under_sum_raises_exception() -> None:
    orders = [
        make_online_order(
            order_id="O1", amount="1000.00", payment_amount="600.00", gateway_txn_id="T1"
        ),
        make_order(
            order_id="O1", amount="1000.00", payment_type=PaymentType.CASH, payment_amount="300.00"
        ),
    ]
    result = build_obligations(orders, amount_tolerance=TOLERANCE)
    assert len(result.order_sum_exceptions) == 1
    exc = result.order_sum_exceptions[0]
    assert exc.reason is ExceptionReason.ORDER_SUM_MISMATCH
    assert exc.status is ObligationStatus.PARTIALLY_MATCHED
    assert exc.expected_amount == Decimal("1000.00")
    assert exc.actual_amount == Decimal("900.00")


def test_split_payment_over_sum_is_excess() -> None:
    orders = [
        make_online_order(
            order_id="O1", amount="1000.00", payment_amount="800.00", gateway_txn_id="T1"
        ),
        make_order(
            order_id="O1", amount="1000.00", payment_type=PaymentType.CASH, payment_amount="400.00"
        ),
    ]
    result = build_obligations(orders, amount_tolerance=TOLERANCE)
    assert result.order_sum_exceptions[0].status is ObligationStatus.EXCESS


def test_sum_within_tolerance_is_ok() -> None:
    orders = [
        make_order(
            order_id="O1", amount="1000.00", payment_type=PaymentType.CASH, payment_amount="999.50"
        ),
    ]
    result = build_obligations(orders, amount_tolerance=TOLERANCE)
    assert not result.order_sum_exceptions
