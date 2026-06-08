"""Tests for the deterministic matcher."""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from reconcile.config import AppSettings, load_app_config
from reconcile.models.domain import (
    ExceptionReason,
    ObligationStatus,
    PaymentType,
    SlaStatus,
)
from reconcile.parsers import read_orders, read_settlements
from reconcile.reconciliation import build_obligations, reconcile, reconcile_keys
from reconcile.reconciliation.matcher import classify_leftovers
from tests.factories import make_obligation, make_settlement

pytestmark = pytest.mark.unit

TOLERANCE = Decimal("1.00")
GRACE = {PaymentType.CASH: 1, PaymentType.UPI: 1, PaymentType.CARD: 2}
AS_OF = date(2026, 6, 8)


# --------------------------------------------------------------------------- #
# Key matching: amount comparison
# --------------------------------------------------------------------------- #


def test_exact_match_by_txn() -> None:
    obligation = make_obligation(expected_amount="1000.00", gateway_txn_id="T1")
    settlement = make_settlement(amount="1000.00", gateway_txn_id="T1")
    result = reconcile_keys([obligation], [settlement], amount_tolerance=TOLERANCE)
    assert len(result.matched) == 1
    assert not result.exceptions
    assert not result.unmatched_settlements


def test_partial_match_is_amount_short() -> None:
    obligation = make_obligation(expected_amount="2000.00", gateway_txn_id="T1")
    settlement = make_settlement(amount="1500.00", gateway_txn_id="T1")
    result = reconcile_keys([obligation], [settlement], amount_tolerance=TOLERANCE)
    assert result.exceptions[0].reason is ExceptionReason.AMOUNT_SHORT
    assert result.exceptions[0].status is ObligationStatus.PARTIALLY_MATCHED


def test_over_settlement_is_amount_excess() -> None:
    obligation = make_obligation(expected_amount="800.00", gateway_txn_id="T1")
    settlement = make_settlement(amount="900.00", gateway_txn_id="T1")
    result = reconcile_keys([obligation], [settlement], amount_tolerance=TOLERANCE)
    assert result.exceptions[0].reason is ExceptionReason.AMOUNT_EXCESS
    assert result.exceptions[0].status is ObligationStatus.EXCESS


def test_within_tolerance_is_matched() -> None:
    obligation = make_obligation(expected_amount="1000.00", gateway_txn_id="T1")
    settlement = make_settlement(amount="1000.50", gateway_txn_id="T1")
    result = reconcile_keys([obligation], [settlement], amount_tolerance=TOLERANCE)
    assert len(result.matched) == 1


def test_duplicate_settlement_detected() -> None:
    obligation = make_obligation(expected_amount="600.00", gateway_txn_id="T1")
    s1 = make_settlement(settlement_id="A", amount="600.00", gateway_txn_id="T1")
    s2 = make_settlement(settlement_id="B", amount="600.00", gateway_txn_id="T1")
    result = reconcile_keys([obligation], [s1, s2], amount_tolerance=TOLERANCE)
    assert result.exceptions[0].reason is ExceptionReason.DUPLICATE_SETTLEMENT
    assert result.exceptions[0].status is ObligationStatus.DUPLICATE
    assert not result.unmatched_settlements


def test_cash_matches_by_order_and_type() -> None:
    obligation = make_obligation(
        order_id="O5",
        payment_type=PaymentType.CASH,
        expected_amount="500.00",
        payment_gateway=None,
        gateway_txn_id=None,
    )
    settlement = make_settlement(
        settlement_id="ST5",
        order_id="O5",
        payment_type=PaymentType.CASH,
        amount="500.00",
        gateway_txn_id=None,
        source="BANK",
    )
    result = reconcile_keys([obligation], [settlement], amount_tolerance=TOLERANCE)
    assert len(result.matched) == 1


# --------------------------------------------------------------------------- #
# Leftover classification
# --------------------------------------------------------------------------- #


def test_unmatched_cash_is_cash_missing() -> None:
    obligation = make_obligation(
        payment_type=PaymentType.CASH, payment_gateway=None, gateway_txn_id=None
    )
    exceptions = classify_leftovers([obligation], [], grace_days=GRACE, as_of_date=AS_OF)
    assert exceptions[0].reason is ExceptionReason.CASH_MISSING


def test_unmatched_online_breached_is_online_missing() -> None:
    obligation = make_obligation(
        payment_type=PaymentType.UPI, order_date=date(2026, 6, 5), gateway_txn_id="T1"
    )
    exceptions = classify_leftovers([obligation], [], grace_days=GRACE, as_of_date=AS_OF)
    assert exceptions[0].reason is ExceptionReason.ONLINE_MISSING
    assert exceptions[0].sla_status is SlaStatus.BREACHED


def test_unmatched_online_within_grace_is_late() -> None:
    obligation = make_obligation(
        payment_type=PaymentType.CARD, order_date=date(2026, 6, 8), gateway_txn_id="T1"
    )
    exceptions = classify_leftovers([obligation], [], grace_days=GRACE, as_of_date=AS_OF)
    assert exceptions[0].reason is ExceptionReason.LATE_SETTLEMENT
    assert exceptions[0].sla_status is SlaStatus.WITHIN_SLA


def test_unmatched_settlement_classified() -> None:
    settlement = make_settlement(settlement_id="X9", gateway_txn_id="UNKNOWN", source="CASHFREE")
    exceptions = classify_leftovers([], [settlement], grace_days=GRACE, as_of_date=AS_OF)
    assert exceptions[0].reason is ExceptionReason.UNMATCHED_SETTLEMENT
    assert exceptions[0].settlement_id == "X9"


def test_unmatched_bank_settlement_has_no_gateway() -> None:
    settlement = make_settlement(settlement_id="B1", gateway_txn_id="UNKNOWN", source="BANK")
    exceptions = classify_leftovers([], [settlement], grace_days=GRACE, as_of_date=AS_OF)
    assert exceptions[0].payment_gateway is None


# --------------------------------------------------------------------------- #
# End-to-end on the committed sample data (exact expectations)
# --------------------------------------------------------------------------- #


def _sample_config() -> object:
    repo_root = Path(__file__).resolve().parents[2]
    settings = AppSettings(
        _env_file=None,
        config_path=repo_root / "config" / "settings.yaml",
    )
    return load_app_config(settings)


def test_full_reconcile_on_samples() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    samples = repo_root / "data" / "samples"
    orders = read_orders(samples / "orders_sample.csv")
    settlements = read_settlements(samples / "settlements_sample.csv")
    config = _sample_config()

    built = build_obligations(orders, amount_tolerance=TOLERANCE)
    assert len(built.obligations) == 13  # 14 rows - 1 cancelled
    assert len(built.order_sum_exceptions) == 1  # O1008

    result = reconcile(built.obligations, settlements, config=config, as_of_date=AS_OF)  # type: ignore[arg-type]

    assert len(result.matched) == 6
    reasons = Counter(exc.reason for exc in result.exceptions)
    assert reasons[ExceptionReason.AMOUNT_SHORT] == 1
    assert reasons[ExceptionReason.AMOUNT_EXCESS] == 1
    assert reasons[ExceptionReason.DUPLICATE_SETTLEMENT] == 1
    assert reasons[ExceptionReason.CASH_MISSING] == 1
    assert reasons[ExceptionReason.ONLINE_MISSING] == 2
    assert reasons[ExceptionReason.LATE_SETTLEMENT] == 1
    assert reasons[ExceptionReason.UNMATCHED_SETTLEMENT] == 2
    assert len(result.unmatched_obligations) == 4
    assert len(result.unmatched_settlements) == 2
