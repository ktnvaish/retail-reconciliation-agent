"""Tests for exception routing rules."""

from __future__ import annotations

import pytest

from reconcile.config import AppConfig
from reconcile.models.domain import (
    ExceptionReason,
    ExceptionRecord,
    ObligationStatus,
    PaymentGateway,
    PaymentType,
    RecipientRole,
)
from reconcile.reconciliation import resolve_targets

pytestmark = pytest.mark.unit


def _exc(**overrides: object) -> ExceptionRecord:
    base: dict[str, object] = {
        "reason": ExceptionReason.CASH_MISSING,
        "status": ObligationStatus.UNMATCHED,
        "order_id": "O1",
        "payment_type": PaymentType.CASH,
    }
    base.update(overrides)
    return ExceptionRecord.model_validate(base)


def test_cash_missing_routes_to_store_manager(app_config: AppConfig) -> None:
    targets = resolve_targets(_exc(), app_config)
    assert len(targets) == 1
    assert targets[0].role is RecipientRole.STORE_MANAGER
    assert targets[0].email == "store-manager@demo.local"


def test_online_missing_routes_to_gateway(app_config: AppConfig) -> None:
    exc = _exc(
        reason=ExceptionReason.ONLINE_MISSING,
        payment_type=PaymentType.UPI,
        payment_gateway=PaymentGateway.PAYU,
    )
    targets = resolve_targets(exc, app_config)
    assert targets[0].role is RecipientRole.PAYMENT_GATEWAY
    assert targets[0].email == "payu-support@demo.local"


def test_amount_short_routes_to_two_recipients(app_config: AppConfig) -> None:
    exc = _exc(
        reason=ExceptionReason.AMOUNT_SHORT,
        status=ObligationStatus.PARTIALLY_MATCHED,
        payment_type=PaymentType.CARD,
        payment_gateway=PaymentGateway.RAZORPAY,
    )
    targets = resolve_targets(exc, app_config)
    roles = {t.role for t in targets}
    assert roles == {RecipientRole.PAYMENT_GATEWAY, RecipientRole.STORE_MANAGER}


def test_duplicate_routes_to_gateway_and_bank(app_config: AppConfig) -> None:
    exc = _exc(
        reason=ExceptionReason.DUPLICATE_SETTLEMENT,
        status=ObligationStatus.DUPLICATE,
        payment_type=PaymentType.UPI,
        payment_gateway=PaymentGateway.RAZORPAY,
    )
    targets = resolve_targets(exc, app_config)
    roles = {t.role for t in targets}
    assert roles == {RecipientRole.PAYMENT_GATEWAY, RecipientRole.BANK}


def test_responsible_party_overrides_default(app_config: AppConfig) -> None:
    exc = _exc(
        reason=ExceptionReason.AMOUNT_SHORT,
        status=ObligationStatus.PARTIALLY_MATCHED,
        payment_type=PaymentType.CARD,
        payment_gateway=PaymentGateway.RAZORPAY,
        responsible_party=RecipientRole.ADMIN,
    )
    targets = resolve_targets(exc, app_config)
    assert len(targets) == 1
    assert targets[0].role is RecipientRole.ADMIN
    assert targets[0].email == "admin@demo.local"


def test_mismatch_key_is_stable_and_role_specific(app_config: AppConfig) -> None:
    exc = _exc(
        reason=ExceptionReason.AMOUNT_SHORT,
        status=ObligationStatus.PARTIALLY_MATCHED,
        payment_type=PaymentType.CARD,
        payment_gateway=PaymentGateway.RAZORPAY,
    )
    first = resolve_targets(exc, app_config)
    second = resolve_targets(exc, app_config)
    # Deterministic across calls.
    assert [t.mismatch_key for t in first] == [t.mismatch_key for t in second]
    # Distinct per role.
    assert len({t.mismatch_key for t in first}) == len(first)


def test_unmatched_settlement_gateway_falls_back_to_admin(app_config: AppConfig) -> None:
    # Settlement from BANK has no gateway -> PAYMENT_GATEWAY role resolves to admin.
    exc = _exc(
        reason=ExceptionReason.UNMATCHED_SETTLEMENT,
        status=ObligationStatus.UNMATCHED,
        order_id=None,
        settlement_id="S9",
        payment_type=PaymentType.CARD,
        payment_gateway=None,
    )
    targets = resolve_targets(exc, app_config)
    emails = {t.role: t.email for t in targets}
    assert emails[RecipientRole.BANK] == "bank-ops@demo.local"
    assert emails[RecipientRole.PAYMENT_GATEWAY] == "admin@demo.local"
