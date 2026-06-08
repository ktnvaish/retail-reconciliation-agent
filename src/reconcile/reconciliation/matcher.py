"""Deterministic reconciliation engine.

No LLM is ever involved here. Matching proceeds by exact keys:

1. ``gateway_txn_id`` (online obligations), then
2. ``(order_id, payment_type)`` (a fallback that also handles cash deposits and
   split payments).

Matched-by-key obligations are then compared on amount. Anything left unmatched
on either side is classified into exceptions (cash/online missing, late, or an
unmatched settlement). The optional fuzzy-matching step (in the agent) runs
*between* key matching and leftover classification, which is why those two
concerns are exposed as separate functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from reconcile.config import AppConfig
from reconcile.models.domain import (
    ExceptionReason,
    ExceptionRecord,
    MatchedPair,
    Obligation,
    ObligationStatus,
    PaymentGateway,
    PaymentType,
    Settlement,
    SettlementSource,
    SlaStatus,
)
from reconcile.reconciliation.sla import compute_age_days, sla_status


@dataclass(frozen=True)
class KeyMatchResult:
    """Outcome of pure key-based matching, before leftovers are classified."""

    matched: list[MatchedPair]
    exceptions: list[ExceptionRecord]
    unmatched_obligations: list[Obligation]
    unmatched_settlements: list[Settlement]


@dataclass(frozen=True)
class ReconciliationResult:
    """Full deterministic reconciliation outcome (no fuzzy matching applied)."""

    matched: list[MatchedPair]
    exceptions: list[ExceptionRecord]
    unmatched_obligations: list[Obligation]
    unmatched_settlements: list[Settlement]


_AMOUNT_REASON = {
    ObligationStatus.PARTIALLY_MATCHED: ExceptionReason.AMOUNT_SHORT,
    ObligationStatus.EXCESS: ExceptionReason.AMOUNT_EXCESS,
}


def _amount_status(expected: Decimal, actual: Decimal, tolerance: Decimal) -> ObligationStatus:
    diff = actual - expected
    if abs(diff) <= tolerance:
        return ObligationStatus.MATCHED
    return ObligationStatus.PARTIALLY_MATCHED if diff < 0 else ObligationStatus.EXCESS


def _gateway_from_source(source: SettlementSource) -> PaymentGateway | None:
    try:
        return PaymentGateway(source.value)
    except ValueError:
        return None


def _amount_exception(
    obligation: Obligation, settlement: Settlement, status: ObligationStatus
) -> ExceptionRecord:
    return ExceptionRecord(
        reason=_AMOUNT_REASON[status],
        status=status,
        order_id=obligation.order_id,
        settlement_id=settlement.settlement_id,
        payment_type=obligation.payment_type,
        store_id=obligation.store_id,
        payment_gateway=obligation.payment_gateway,
        expected_amount=obligation.expected_amount,
        actual_amount=settlement.amount,
        responsible_party=obligation.responsible_party,
        detail=(
            f"Expected {obligation.expected_amount}, settled {settlement.amount} "
            f"(settlement {settlement.settlement_id})."
        ),
    )


def _duplicate_exception(obligation: Obligation, settlements: list[Settlement]) -> ExceptionRecord:
    ids = ", ".join(s.settlement_id for s in settlements)
    return ExceptionRecord(
        reason=ExceptionReason.DUPLICATE_SETTLEMENT,
        status=ObligationStatus.DUPLICATE,
        order_id=obligation.order_id,
        settlement_id=settlements[0].settlement_id,
        payment_type=obligation.payment_type,
        store_id=obligation.store_id,
        payment_gateway=obligation.payment_gateway,
        expected_amount=obligation.expected_amount,
        actual_amount=settlements[0].amount,
        responsible_party=obligation.responsible_party,
        detail=f"{len(settlements)} settlements satisfy this obligation: {ids}.",
    )


def reconcile_keys(
    obligations: list[Obligation],
    settlements: list[Settlement],
    *,
    amount_tolerance: Decimal,
) -> KeyMatchResult:
    """Match obligations to settlements by exact keys and compare amounts."""
    by_txn: dict[str, list[Settlement]] = {}
    by_order_type: dict[tuple[str, PaymentType], list[Settlement]] = {}
    for settlement in settlements:
        if settlement.gateway_txn_id:
            by_txn.setdefault(settlement.gateway_txn_id, []).append(settlement)
        if settlement.order_id:
            by_order_type.setdefault((settlement.order_id, settlement.payment_type), []).append(
                settlement
            )

    consumed: set[str] = set()

    def live(candidates: list[Settlement]) -> list[Settlement]:
        return [s for s in candidates if s.settlement_id not in consumed]

    matched: list[MatchedPair] = []
    exceptions: list[ExceptionRecord] = []
    unmatched_obligations: list[Obligation] = []

    for obligation in obligations:
        candidates: list[Settlement] = []
        if obligation.gateway_txn_id:
            candidates = live(by_txn.get(obligation.gateway_txn_id, []))
        if not candidates:
            candidates = live(by_order_type.get((obligation.order_id, obligation.payment_type), []))

        if not candidates:
            unmatched_obligations.append(obligation)
            continue

        if len(candidates) > 1:
            for settlement in candidates:
                consumed.add(settlement.settlement_id)
            exceptions.append(_duplicate_exception(obligation, candidates))
            continue

        settlement = candidates[0]
        consumed.add(settlement.settlement_id)
        status = _amount_status(obligation.expected_amount, settlement.amount, amount_tolerance)
        if status is ObligationStatus.MATCHED:
            matched.append(MatchedPair(obligation=obligation, settlement=settlement))
        else:
            exceptions.append(_amount_exception(obligation, settlement, status))

    unmatched_settlements = [s for s in settlements if s.settlement_id not in consumed]
    return KeyMatchResult(
        matched=matched,
        exceptions=exceptions,
        unmatched_obligations=unmatched_obligations,
        unmatched_settlements=unmatched_settlements,
    )


def _missing_obligation_exception(
    obligation: Obligation,
    *,
    grace_days: dict[PaymentType, int],
    as_of_date: date,
) -> ExceptionRecord:
    status_value, age = sla_status(obligation, as_of_date, grace_days)

    if not obligation.payment_type.is_online:
        reason = ExceptionReason.CASH_MISSING
    elif status_value is SlaStatus.WITHIN_SLA:
        reason = ExceptionReason.LATE_SETTLEMENT
    else:
        # Breached, or no grace configured -> treat as a hard miss.
        reason = ExceptionReason.ONLINE_MISSING

    return ExceptionRecord(
        reason=reason,
        status=ObligationStatus.UNMATCHED,
        order_id=obligation.order_id,
        payment_type=obligation.payment_type,
        store_id=obligation.store_id,
        payment_gateway=obligation.payment_gateway,
        expected_amount=obligation.expected_amount,
        actual_amount=None,
        responsible_party=obligation.responsible_party,
        age_days=age,
        sla_status=status_value,
        detail=f"No settlement found for obligation {obligation.obligation_id}.",
    )


def _unmatched_settlement_exception(settlement: Settlement, as_of_date: date) -> ExceptionRecord:
    return ExceptionRecord(
        reason=ExceptionReason.UNMATCHED_SETTLEMENT,
        status=ObligationStatus.UNMATCHED,
        settlement_id=settlement.settlement_id,
        payment_type=settlement.payment_type,
        payment_gateway=_gateway_from_source(settlement.source),
        actual_amount=settlement.amount,
        age_days=compute_age_days(settlement.settlement_date, as_of_date),
        detail=f"Settlement {settlement.settlement_id} has no matching order.",
    )


def classify_leftovers(
    unmatched_obligations: list[Obligation],
    unmatched_settlements: list[Settlement],
    *,
    grace_days: dict[PaymentType, int],
    as_of_date: date,
) -> list[ExceptionRecord]:
    """Turn leftover unmatched obligations and settlements into exceptions."""
    exceptions: list[ExceptionRecord] = [
        _missing_obligation_exception(obligation, grace_days=grace_days, as_of_date=as_of_date)
        for obligation in unmatched_obligations
    ]
    exceptions.extend(
        _unmatched_settlement_exception(settlement, as_of_date)
        for settlement in unmatched_settlements
    )
    return exceptions


def reconcile(
    obligations: list[Obligation],
    settlements: list[Settlement],
    *,
    config: AppConfig,
    as_of_date: date,
) -> ReconciliationResult:
    """Full deterministic reconciliation (key matching + leftover classification).

    The agent uses :func:`reconcile_keys` and :func:`classify_leftovers`
    separately so it can interpose fuzzy matching; this convenience wrapper is
    the fuzzy-disabled path used by tests and simple callers.
    """
    key_result = reconcile_keys(
        obligations, settlements, amount_tolerance=config.reconciliation.amount_tolerance
    )
    leftovers = classify_leftovers(
        key_result.unmatched_obligations,
        key_result.unmatched_settlements,
        grace_days=config.reconciliation.sla_grace_days,
        as_of_date=as_of_date,
    )
    return ReconciliationResult(
        matched=key_result.matched,
        exceptions=key_result.exceptions + leftovers,
        unmatched_obligations=key_result.unmatched_obligations,
        unmatched_settlements=key_result.unmatched_settlements,
    )
