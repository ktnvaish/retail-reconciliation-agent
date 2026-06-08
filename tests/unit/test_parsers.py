"""Tests for the orders and settlements parsers."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from reconcile.models.domain import OrderStatus, PaymentType, SettlementSource
from reconcile.parsers import read_orders, read_settlements
from reconcile.parsers.base import ParseError

pytestmark = pytest.mark.unit

EXPECTED_ORDER_ROWS = 14
EXPECTED_SETTLEMENT_ROWS = 12


# --------------------------------------------------------------------------- #
# Happy path: the committed sample files parse cleanly in both formats
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_read_orders_sample(samples_dir: Path, suffix: str) -> None:
    orders = read_orders(samples_dir / f"orders_sample{suffix}")
    assert len(orders) == EXPECTED_ORDER_ROWS
    by_id = {(o.order_id, o.payment_type) for o in orders}
    assert ("O1001", PaymentType.CARD) in by_id
    # O1008 is a split payment: two rows sharing the order id.
    assert sum(1 for o in orders if o.order_id == "O1008") == 2


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_read_settlements_sample(samples_dir: Path, suffix: str) -> None:
    settlements = read_settlements(samples_dir / f"settlements_sample{suffix}")
    assert len(settlements) == EXPECTED_SETTLEMENT_ROWS
    ids = {s.settlement_id for s in settlements}
    assert {"S2007A", "S2007B"} <= ids  # duplicate-settlement pair present


def test_orders_decimal_amounts_are_exact(samples_dir: Path) -> None:
    orders = read_orders(samples_dir / "orders_sample.csv")
    o1001 = next(o for o in orders if o.order_id == "O1001")
    assert o1001.amount == Decimal("1000.00")
    assert isinstance(o1001.amount, Decimal)


def test_cancelled_order_is_parsed(samples_dir: Path) -> None:
    orders = read_orders(samples_dir / "orders_sample.csv")
    o1010 = next(o for o in orders if o.order_id == "O1010")
    assert o1010.status is OrderStatus.CANCELLED


def test_cash_order_has_no_gateway(samples_dir: Path) -> None:
    orders = read_orders(samples_dir / "orders_sample.csv")
    o1002 = next(o for o in orders if o.order_id == "O1002")
    assert o1002.payment_type is PaymentType.CASH
    assert o1002.payment_gateway is None
    assert o1002.gateway_txn_id is None


# --------------------------------------------------------------------------- #
# Settlement-specific behavior
# --------------------------------------------------------------------------- #


def test_settlement_net_amount_defaults_to_amount_minus_fee() -> None:
    csv = (
        b"settlement_id,settlement_date,payment_type,amount,fee,source\n"
        b"S1,2026-06-07,CARD,1000.00,20.00,RAZORPAY\n"
    )
    settlements = read_settlements(csv, filename="s.csv")
    assert settlements[0].net_amount == Decimal("980.00")
    assert settlements[0].source is SettlementSource.RAZORPAY


def test_settlement_explicit_net_amount_is_respected() -> None:
    csv = (
        b"settlement_id,settlement_date,payment_type,amount,fee,net_amount,source\n"
        b"S1,2026-06-07,CARD,1000.00,20.00,975.00,RAZORPAY\n"
    )
    settlements = read_settlements(csv, filename="s.csv")
    assert settlements[0].net_amount == Decimal("975.00")


# --------------------------------------------------------------------------- #
# Validation failures
# --------------------------------------------------------------------------- #


def test_online_order_without_txn_id_raises() -> None:
    csv = (
        b"order_id,order_date,store_id,amount,payment_type,payment_amount,status\n"
        b"O1,2026-06-06,S1,1000.00,CARD,1000.00,PLACED\n"
    )
    with pytest.raises(ParseError) as exc:
        read_orders(csv, filename="o.csv")
    assert any("gateway_txn_id" in e for e in exc.value.errors)


def test_missing_required_column_raises() -> None:
    csv = b"order_id,order_date,store_id\nO1,2026-06-06,S1\n"
    with pytest.raises(ParseError) as exc:
        read_orders(csv, filename="o.csv")
    assert "missing required column" in str(exc.value).lower()


def test_empty_file_raises() -> None:
    csv = b"order_id,order_date,store_id,amount,payment_type,payment_amount,status\n"
    with pytest.raises(ParseError) as exc:
        read_orders(csv, filename="o.csv")
    assert "no data rows" in str(exc.value).lower()


def test_unsupported_extension_raises() -> None:
    with pytest.raises(ParseError) as exc:
        read_orders(b"irrelevant", filename="data.txt")
    assert "unsupported file type" in str(exc.value).lower()


def test_invalid_enum_reports_row_number() -> None:
    csv = (
        b"order_id,order_date,store_id,amount,payment_type,payment_amount,status\n"
        b"O1,2026-06-06,S1,500.00,BITCOIN,500.00,PLACED\n"
    )
    with pytest.raises(ParseError) as exc:
        read_orders(csv, filename="o.csv")
    assert any("row 2" in e for e in exc.value.errors)
