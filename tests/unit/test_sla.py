"""Tests for SLA evaluation."""

from __future__ import annotations

from datetime import date

import pytest

from reconcile.models.domain import PaymentType, SlaStatus
from reconcile.reconciliation import sla_status
from tests.factories import make_obligation

pytestmark = pytest.mark.unit

GRACE = {
    PaymentType.CASH: 1,
    PaymentType.UPI: 1,
    PaymentType.CARD: 2,
    PaymentType.NETBANKING: 2,
    PaymentType.WALLET: 1,
}
AS_OF = date(2026, 6, 8)


def test_online_within_grace() -> None:
    obligation = make_obligation(payment_type=PaymentType.CARD, order_date=date(2026, 6, 7))
    status, age = sla_status(obligation, AS_OF, GRACE)
    assert status is SlaStatus.WITHIN_SLA
    assert age == 1


def test_online_breached() -> None:
    obligation = make_obligation(
        payment_type=PaymentType.UPI, order_date=date(2026, 6, 5), gateway_txn_id="T1"
    )
    status, age = sla_status(obligation, AS_OF, GRACE)
    assert status is SlaStatus.BREACHED
    assert age == 3


def test_online_exactly_at_grace_boundary_is_within() -> None:
    obligation = make_obligation(payment_type=PaymentType.CARD, order_date=date(2026, 6, 6))
    status, _ = sla_status(obligation, AS_OF, GRACE)
    assert status is SlaStatus.WITHIN_SLA  # age 2 == grace 2


def test_cash_is_not_applicable() -> None:
    obligation = make_obligation(
        payment_type=PaymentType.CASH, gateway_txn_id=None, payment_gateway=None
    )
    status, _ = sla_status(obligation, AS_OF, GRACE)
    assert status is SlaStatus.NA


def test_missing_grace_config_is_not_applicable() -> None:
    obligation = make_obligation(payment_type=PaymentType.CARD)
    status, _ = sla_status(obligation, AS_OF, {})
    assert status is SlaStatus.NA
