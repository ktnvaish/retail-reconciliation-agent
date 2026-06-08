"""Tests for the LLM clients (deterministic mock + Groq adapter with a fake model)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from reconcile.agent.llm import GroqLLMClient, LLMBudgetExceededError, MockLLMClient
from reconcile.agent.schemas import (
    EmailDraft,
    ExceptionDecision,
    FuzzyPairing,
    FuzzyProposal,
    Severity,
)
from reconcile.models.domain import (
    ExceptionReason,
    ExceptionRecord,
    ObligationStatus,
    PaymentGateway,
    PaymentType,
    RecipientRole,
    SlaStatus,
)
from tests.factories import make_obligation, make_settlement

pytestmark = pytest.mark.unit

THRESHOLD = Decimal("1000.00")


def _exc(reason: ExceptionReason, **overrides: Any) -> ExceptionRecord:
    base: dict[str, Any] = {
        "reason": reason,
        "status": ObligationStatus.UNMATCHED,
        "order_id": "O1",
        "payment_type": PaymentType.CARD,
        "expected_amount": Decimal("500.00"),
    }
    base.update(overrides)
    return ExceptionRecord.model_validate(base)


# --------------------------------------------------------------------------- #
# MockLLMClient
# --------------------------------------------------------------------------- #


def test_mock_decide_action_mapping() -> None:
    client = MockLLMClient()
    cash = client.decide(
        _exc(ExceptionReason.CASH_MISSING), within_sla=False, high_value_threshold=THRESHOLD
    )
    assert cash.action.value == "EMAIL_STORE_MANAGER"

    unmatched = client.decide(
        _exc(ExceptionReason.UNMATCHED_SETTLEMENT), within_sla=False, high_value_threshold=THRESHOLD
    )
    assert unmatched.action.value == "EMAIL_BANK"


def test_mock_decide_late_settlement_waits_within_sla() -> None:
    client = MockLLMClient()
    decision = client.decide(
        _exc(ExceptionReason.LATE_SETTLEMENT, sla_status=SlaStatus.WITHIN_SLA),
        within_sla=True,
        high_value_threshold=THRESHOLD,
    )
    assert decision.action.value == "WAIT"


def test_mock_decide_high_value_severity() -> None:
    client = MockLLMClient()
    decision = client.decide(
        _exc(ExceptionReason.ONLINE_MISSING, expected_amount=Decimal("5000.00")),
        within_sla=False,
        high_value_threshold=THRESHOLD,
    )
    assert decision.severity is Severity.HIGH_VALUE


def test_mock_fuzzy_pairs_matching_amount() -> None:
    client = MockLLMClient()
    obligation = make_obligation(
        order_id="O1",
        expected_amount="1500.00",
        payment_gateway=PaymentGateway.RAZORPAY,
        gateway_txn_id="T1",
    )
    settlement = make_settlement(
        settlement_id="S1",
        amount="1500.00",
        source="RAZORPAY",
        gateway_txn_id=None,
        settlement_date=date(2026, 6, 7),
    )
    proposal = client.propose_fuzzy([obligation], [settlement])
    assert len(proposal.pairings) == 1
    assert proposal.pairings[0].confidence >= 0.85


def test_mock_fuzzy_skips_amount_mismatch() -> None:
    client = MockLLMClient()
    obligation = make_obligation(order_id="O1", expected_amount="1500.00", gateway_txn_id="T1")
    settlement = make_settlement(settlement_id="S1", amount="999.00", gateway_txn_id=None)
    proposal = client.propose_fuzzy([obligation], [settlement])
    assert proposal.pairings == []


def test_fuzzy_pairing_allows_null_ids() -> None:
    # Real models sometimes emit placeholder rows for unmatchable orders;
    # the schema must accept null ids (they are filtered out on application).
    pairing = FuzzyPairing(order_id="O1", settlement_id=None, confidence=0.0, rationale="no match")
    assert pairing.settlement_id is None
    proposal = FuzzyProposal(pairings=[pairing])
    assert proposal.pairings[0].order_id == "O1"


def test_mock_draft_email_contains_facts() -> None:
    client = MockLLMClient()
    draft = client.draft_email(
        _exc(ExceptionReason.CASH_MISSING), RecipientRole.STORE_MANAGER, "email"
    )
    assert "CASH_MISSING" in draft.subject
    assert "Store Manager" in draft.body


# --------------------------------------------------------------------------- #
# GroqLLMClient with a fake underlying model (no network)
# --------------------------------------------------------------------------- #


class _FakeStructured:
    def __init__(self, schema: type) -> None:
        self._schema = schema

    def invoke(self, _prompt: str) -> Any:
        if self._schema is ExceptionDecision:
            return ExceptionDecision(severity=Severity.ROUTINE, action="EMAIL_PG", rationale="ok")
        if self._schema is FuzzyProposal:
            return FuzzyProposal(pairings=[])
        if self._schema is EmailDraft:
            return EmailDraft(subject="s", body="b")
        raise AssertionError("unexpected schema")


class _FakeLLM:
    def with_structured_output(self, schema: type) -> _FakeStructured:
        return _FakeStructured(schema)


def _groq_with_fake(max_calls: int = 10) -> GroqLLMClient:
    client = GroqLLMClient(api_key="test-key", model="fake", max_calls=max_calls)
    client._llm = _FakeLLM()  # type: ignore[assignment]
    return client


def test_groq_decide_returns_structured() -> None:
    client = _groq_with_fake()
    decision = client.decide(
        _exc(ExceptionReason.ONLINE_MISSING), within_sla=False, high_value_threshold=THRESHOLD
    )
    assert decision.action.value == "EMAIL_PG"


def test_groq_propose_fuzzy_uses_model() -> None:
    client = _groq_with_fake()
    proposal = client.propose_fuzzy([make_obligation()], [make_settlement()])
    assert isinstance(proposal, FuzzyProposal)


def test_groq_budget_exceeded() -> None:
    # propose_fuzzy has no fallback, so the budget error surfaces there.
    client = _groq_with_fake(max_calls=0)
    with pytest.raises(LLMBudgetExceededError):
        client.propose_fuzzy([make_obligation()], [make_settlement()])


def test_groq_decide_falls_back_to_rules_on_budget() -> None:
    # decide() degrades to a deterministic rules-based decision instead of failing.
    client = _groq_with_fake(max_calls=0)
    decision = client.decide(
        _exc(ExceptionReason.CASH_MISSING), within_sla=False, high_value_threshold=THRESHOLD
    )
    assert decision.action.value == "EMAIL_STORE_MANAGER"


def test_groq_draft_falls_back_to_template_on_budget() -> None:
    client = _groq_with_fake(max_calls=0)
    draft = client.draft_email(
        _exc(ExceptionReason.CASH_MISSING), RecipientRole.STORE_MANAGER, "email"
    )
    # Budget is exhausted, so the deterministic template is used instead.
    assert "CASH_MISSING" in draft.subject


def test_groq_requires_api_key() -> None:
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        GroqLLMClient(api_key="", model="x", max_calls=1)
