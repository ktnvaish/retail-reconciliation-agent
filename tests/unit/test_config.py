"""Tests for configuration loading and recipient resolution."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest

from reconcile.config import AppSettings, load_app_config
from reconcile.models.domain import PaymentGateway, PaymentType, PlannerAction, RecipientRole

pytestmark = pytest.mark.unit


def test_load_app_config_reads_yaml(settings: AppSettings) -> None:
    config = load_app_config(settings)
    assert config.recipients.store_manager == "store-manager@demo.local"
    assert config.reconciliation.amount_tolerance == Decimal("1.00")
    assert config.reconciliation.sla_grace_days[PaymentType.CARD] == 2
    assert PlannerAction.ESCALATE in config.planner.allowed_actions
    assert config.fuzzy_match.auto_apply_threshold == 0.85


def test_recipient_env_override_takes_precedence(
    make_settings: Callable[..., AppSettings],
) -> None:
    settings = make_settings(
        recipient_store_manager="real-manager@store.com",
        recipient_pg_razorpay="ops@razorpay.com",
    )
    config = load_app_config(settings)
    assert config.recipients.store_manager == "real-manager@store.com"
    assert config.recipients.payment_gateways[PaymentGateway.RAZORPAY] == "ops@razorpay.com"
    # Untouched roles keep their YAML defaults.
    assert config.recipients.bank == "bank-ops@demo.local"


def test_recipient_for_role_resolves_gateway(settings: AppSettings) -> None:
    config = load_app_config(settings)
    email = config.recipients.for_role(RecipientRole.PAYMENT_GATEWAY, PaymentGateway.PAYU)
    assert email == "payu-support@demo.local"
    # Payment gateway role without a gateway falls back to admin.
    assert config.recipients.for_role(RecipientRole.PAYMENT_GATEWAY) == "admin@demo.local"


def test_missing_config_file_raises(make_settings: Callable[..., AppSettings]) -> None:
    settings = make_settings(config_path="does/not/exist.yaml")
    with pytest.raises(FileNotFoundError):
        load_app_config(settings)
