"""LLM client abstraction.

The agent talks to an :class:`LLMClient` rather than a chat model directly. This
keeps LangChain/Groq usage isolated, makes every LLM interaction return a
validated Pydantic object, and provides a deterministic mock that lets the whole
pipeline run offline (in tests, CI, and key-less demos).

The LLM is used only for judgement: proposing fuzzy matches, deciding a
severity + next action per exception, and drafting email text. It is never in
the deterministic matching path.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, TypeVar, cast, runtime_checkable

from pydantic import BaseModel

from reconcile.agent.prompts import decide_prompt, draft_prompt, fuzzy_prompt
from reconcile.agent.schemas import (
    EmailDraft,
    ExceptionDecision,
    FuzzyPairing,
    FuzzyProposal,
    Severity,
)
from reconcile.config import AppSettings
from reconcile.logging_setup import get_logger
from reconcile.models.domain import (
    ExceptionReason,
    ExceptionRecord,
    Obligation,
    PlannerAction,
    RecipientRole,
    Settlement,
)
from reconcile.notifications.retry import call_with_retry

_log = get_logger("llm")

T = TypeVar("T", bound=BaseModel)

_NEEDS_REVIEW_REASONS = {
    ExceptionReason.AMOUNT_SHORT,
    ExceptionReason.AMOUNT_EXCESS,
    ExceptionReason.DUPLICATE_SETTLEMENT,
    ExceptionReason.FUZZY_MATCH_REVIEW,
    ExceptionReason.ORDER_SUM_MISMATCH,
}

_ACTION_BY_REASON = {
    ExceptionReason.CASH_MISSING: PlannerAction.EMAIL_STORE_MANAGER,
    ExceptionReason.ONLINE_MISSING: PlannerAction.EMAIL_PG,
    ExceptionReason.AMOUNT_SHORT: PlannerAction.EMAIL_PG,
    ExceptionReason.AMOUNT_EXCESS: PlannerAction.EMAIL_PG,
    ExceptionReason.DUPLICATE_SETTLEMENT: PlannerAction.EMAIL_PG,
    ExceptionReason.UNMATCHED_SETTLEMENT: PlannerAction.EMAIL_BANK,
    ExceptionReason.ORDER_SUM_MISMATCH: PlannerAction.EMAIL_STORE_MANAGER,
    ExceptionReason.FUZZY_MATCH_REVIEW: PlannerAction.ESCALATE,
}


class LLMTransientError(Exception):
    """A retryable LLM/provider failure."""


class LLMBudgetExceededError(Exception):
    """Raised when a run exceeds its configured LLM call budget."""


@runtime_checkable
class LLMClient(Protocol):
    """Judgement calls the agent delegates to an LLM (or its mock)."""

    def propose_fuzzy(
        self, obligations: list[Obligation], settlements: list[Settlement]
    ) -> FuzzyProposal: ...

    def decide(
        self, exception: ExceptionRecord, *, within_sla: bool, high_value_threshold: Decimal
    ) -> ExceptionDecision: ...

    def draft_email(
        self, exception: ExceptionRecord, role: RecipientRole, tag: str
    ) -> EmailDraft: ...


# --------------------------------------------------------------------------- #
# Deterministic mock (offline path + template fallback)
# --------------------------------------------------------------------------- #


class MockLLMClient:
    """A deterministic, rules-based stand-in for a real LLM."""

    name = "mock"

    def propose_fuzzy(
        self, obligations: list[Obligation], settlements: list[Settlement]
    ) -> FuzzyProposal:
        pairings: list[FuzzyPairing] = []
        used: set[str] = set()
        for obligation in obligations:
            for settlement in settlements:
                if settlement.settlement_id in used:
                    continue
                if settlement.amount != obligation.expected_amount:
                    continue
                confidence = _fuzzy_confidence(obligation, settlement)
                used.add(settlement.settlement_id)
                pairings.append(
                    FuzzyPairing(
                        order_id=obligation.order_id,
                        settlement_id=settlement.settlement_id,
                        confidence=confidence,
                        rationale=(
                            f"Amount {obligation.expected_amount} matches; "
                            f"source {settlement.source.value}."
                        ),
                    )
                )
                break
        return FuzzyProposal(pairings=pairings)

    def decide(
        self, exception: ExceptionRecord, *, within_sla: bool, high_value_threshold: Decimal
    ) -> ExceptionDecision:
        action = _mock_action(exception, within_sla)
        severity = _mock_severity(exception, high_value_threshold)
        return ExceptionDecision(
            severity=severity,
            action=action,
            rationale=f"{exception.reason.value} -> {action.value} (severity {severity.value}).",
        )

    def draft_email(self, exception: ExceptionRecord, role: RecipientRole, tag: str) -> EmailDraft:
        return EmailDraft(
            subject=_template_subject(exception), body=_template_body(exception, role, tag)
        )


# --------------------------------------------------------------------------- #
# Groq-backed client
# --------------------------------------------------------------------------- #


class GroqLLMClient:
    """LLM client backed by Groq via LangChain, with retries and a call budget."""

    name = "groq"

    def __init__(self, *, api_key: str, model: str, max_calls: int) -> None:
        if not api_key:
            raise ValueError("GROQ_API_KEY is required when MOCK_LLM is false")
        from langchain_groq import ChatGroq

        # ChatGroq accepts `model`/`api_key` via pydantic aliases at runtime;
        # mypy only sees the canonical field names, hence the ignore.
        self._llm = ChatGroq(api_key=api_key, model=model, temperature=0)  # type: ignore[call-arg]
        self._max_calls = max_calls
        self._calls = 0
        # Template fallback reuses the deterministic mock for email bodies.
        self._fallback = MockLLMClient()

    def propose_fuzzy(
        self, obligations: list[Obligation], settlements: list[Settlement]
    ) -> FuzzyProposal:
        prompt = fuzzy_prompt(_obligations_text(obligations), _settlements_text(settlements))
        return self._invoke(FuzzyProposal, prompt)

    def decide(
        self, exception: ExceptionRecord, *, within_sla: bool, high_value_threshold: Decimal
    ) -> ExceptionDecision:
        prompt = decide_prompt(
            exception, within_sla=within_sla, high_value_threshold=str(high_value_threshold)
        )
        return self._invoke(ExceptionDecision, prompt)

    def draft_email(self, exception: ExceptionRecord, role: RecipientRole, tag: str) -> EmailDraft:
        try:
            return self._invoke(EmailDraft, draft_prompt(exception, role, tag))
        except (LLMTransientError, LLMBudgetExceededError) as exc:
            _log.warning("draft_fallback_to_template", error=str(exc))
            return self._fallback.draft_email(exception, role, tag)

    def _invoke(self, schema: type[T], prompt: str) -> T:
        self._consume_budget()
        structured = self._llm.with_structured_output(schema)

        def call() -> object:
            try:
                return structured.invoke(prompt)
            except Exception as exc:  # provider/network errors are transient
                raise LLMTransientError(str(exc)) from exc

        result = call_with_retry(
            call, attempts=3, min_seconds=1.0, max_seconds=8.0, retry_on=LLMTransientError
        )
        return cast(T, result)

    def _consume_budget(self) -> None:
        self._calls += 1
        if self._calls > self._max_calls:
            raise LLMBudgetExceededError(f"Exceeded LLM call budget of {self._max_calls}")


def build_llm_client(settings: AppSettings) -> LLMClient:
    """Pick the LLM client implementation based on settings."""
    if settings.mock_llm:
        return MockLLMClient()
    return GroqLLMClient(
        api_key=settings.groq_api_key,
        model=settings.llm_model,
        max_calls=settings.max_llm_calls,
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _fuzzy_confidence(obligation: Obligation, settlement: Settlement) -> float:
    date_close = abs((settlement.settlement_date - obligation.order_date).days) <= 3
    source_matches = (
        obligation.payment_gateway is not None
        and settlement.source.value == obligation.payment_gateway.value
    )
    if source_matches and date_close:
        return 0.9
    if date_close:
        return 0.6
    return 0.5


def _mock_action(exception: ExceptionRecord, within_sla: bool) -> PlannerAction:
    if exception.reason is ExceptionReason.LATE_SETTLEMENT:
        return PlannerAction.WAIT if within_sla else PlannerAction.EMAIL_PG
    return _ACTION_BY_REASON.get(exception.reason, PlannerAction.ESCALATE)


def _mock_severity(exception: ExceptionRecord, threshold: Decimal) -> Severity:
    amounts = [a for a in (exception.expected_amount, exception.actual_amount) if a is not None]
    if any(a >= threshold for a in amounts):
        return Severity.HIGH_VALUE
    if exception.reason in _NEEDS_REVIEW_REASONS:
        return Severity.NEEDS_REVIEW
    return Severity.ROUTINE


def _template_subject(exception: ExceptionRecord) -> str:
    ref = exception.order_id or exception.settlement_id or "unknown"
    return f"[Reconciliation] {exception.reason.value} - {ref}"


def _template_body(exception: ExceptionRecord, role: RecipientRole, tag: str) -> str:
    action = {
        "recheck": "Please re-verify and re-upload the corrected data.",
        "escalate": "This item needs manual review.",
    }.get(tag, "Please investigate and confirm the correct settlement.")
    lines = [
        f"Hello {role.value.replace('_', ' ').title()},",
        "",
        f"A reconciliation exception was detected: {exception.reason.value}.",
        f"  Order:       {exception.order_id or 'n/a'}",
        f"  Settlement:  {exception.settlement_id or 'n/a'}",
        f"  Payment:     {exception.payment_type.value if exception.payment_type else 'n/a'}",
        f"  Expected:    {exception.expected_amount if exception.expected_amount is not None else 'n/a'}",
        f"  Actual:      {exception.actual_amount if exception.actual_amount is not None else 'n/a'}",
    ]
    if exception.detail:
        lines.append(f"  Detail:      {exception.detail}")
    lines.extend(["", action, "", "— ReconcileFlow Agent"])
    return "\n".join(lines)


def _obligations_text(obligations: list[Obligation]) -> str:
    return (
        "\n".join(
            f"- order_id={o.order_id} type={o.payment_type.value} amount={o.expected_amount} "
            f"gateway={o.payment_gateway.value if o.payment_gateway else 'n/a'} date={o.order_date}"
            for o in obligations
        )
        or "(none)"
    )


def _settlements_text(settlements: list[Settlement]) -> str:
    return (
        "\n".join(
            f"- settlement_id={s.settlement_id} type={s.payment_type.value} amount={s.amount} "
            f"source={s.source.value} date={s.settlement_date}"
            for s in settlements
        )
        or "(none)"
    )


# Exported names.
__all__ = [
    "GroqLLMClient",
    "LLMBudgetExceededError",
    "LLMClient",
    "LLMTransientError",
    "MockLLMClient",
    "build_llm_client",
]
