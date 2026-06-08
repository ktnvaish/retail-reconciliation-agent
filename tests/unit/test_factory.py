"""Tests for the notifier factory."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from reconcile.config import AppSettings
from reconcile.notifications.factory import build_notifier

pytestmark = pytest.mark.unit


def test_factory_builds_mock(settings: AppSettings) -> None:
    assert build_notifier(settings).name == "mock"


def test_factory_builds_resend(make_settings: Callable[..., AppSettings]) -> None:
    settings = make_settings(notifier="resend", resend_api_key="re_test", resend_from="a@b.com")
    assert build_notifier(settings).name == "resend"


def test_factory_resend_requires_key(make_settings: Callable[..., AppSettings]) -> None:
    settings = make_settings(notifier="resend", resend_api_key="")
    with pytest.raises(ValueError, match="RESEND_API_KEY"):
        build_notifier(settings)


def test_factory_builds_smtp(make_settings: Callable[..., AppSettings]) -> None:
    settings = make_settings(
        notifier="smtp",
        smtp_host="smtp.example.com",
        smtp_user="user",
        smtp_password="secret",
        smtp_from="from@example.com",
    )
    assert build_notifier(settings).name == "smtp"
