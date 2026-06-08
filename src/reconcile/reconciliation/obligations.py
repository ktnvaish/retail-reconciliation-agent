"""Build reconciliation obligations from order rows and validate order sums.

Each ``PLACED`` order row becomes one :class:`Obligation`. Independently, the
payment rows of an order must sum to the order's gross total; a discrepancy
yields an order-level ``ORDER_SUM_MISMATCH`` exception (which is *separate* from
how the individual obligations reconcile against settlements).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from reconcile.models.domain import (
    ExceptionReason,
    ExceptionRecord,
    Obligation,
    ObligationStatus,
    Order,
    OrderStatus,
    make_obligation_id,
)


@dataclass(frozen=True)
class ObligationBuildResult:
    """Obligations to reconcile, plus any order-level sum-mismatch exceptions."""

    obligations: list[Obligation]
    order_sum_exceptions: list[ExceptionRecord]


def _to_obligation(order: Order, seq: int) -> Obligation:
    return Obligation(
        obligation_id=make_obligation_id(
            order.order_id, order.payment_type, order.gateway_txn_id, seq
        ),
        order_id=order.order_id,
        order_date=order.order_date,
        store_id=order.store_id,
        payment_type=order.payment_type,
        expected_amount=order.payment_amount,
        payment_gateway=order.payment_gateway,
        gateway_txn_id=order.gateway_txn_id,
        responsible_party=order.responsible_party,
        customer_name=order.customer_name,
        customer_email=order.customer_email,
    )


def _group_by_order(orders: list[Order]) -> dict[str, list[Order]]:
    """Group rows by ``order_id``, preserving first-seen order."""
    grouped: dict[str, list[Order]] = {}
    for order in orders:
        grouped.setdefault(order.order_id, []).append(order)
    return grouped


def _order_sum_exception(
    order_id: str, rows: list[Order], tolerance: Decimal
) -> ExceptionRecord | None:
    """Return an ``ORDER_SUM_MISMATCH`` exception if the row amounts don't sum to the total."""
    total = rows[0].amount
    paid = sum((row.payment_amount for row in rows), Decimal("0.00"))
    if abs(paid - total) <= tolerance:
        return None

    status = ObligationStatus.EXCESS if paid > total else ObligationStatus.PARTIALLY_MATCHED
    override = next((row.responsible_party for row in rows if row.responsible_party), None)
    return ExceptionRecord(
        reason=ExceptionReason.ORDER_SUM_MISMATCH,
        status=status,
        order_id=order_id,
        store_id=rows[0].store_id,
        expected_amount=total,
        actual_amount=paid,
        responsible_party=override,
        detail=(
            f"Order payment rows sum to {paid} but the order total is {total} "
            f"(difference {paid - total})."
        ),
    )


def build_obligations(orders: list[Order], *, amount_tolerance: Decimal) -> ObligationBuildResult:
    """Explode ``PLACED`` order rows into obligations and validate per-order sums.

    Cancelled rows are ignored entirely. Orders with no placed rows are skipped.
    """
    obligations: list[Obligation] = []
    sum_exceptions: list[ExceptionRecord] = []

    for order_id, rows in _group_by_order(orders).items():
        placed = [row for row in rows if row.status is OrderStatus.PLACED]
        if not placed:
            continue

        for seq, order in enumerate(placed):
            obligations.append(_to_obligation(order, seq))

        exception = _order_sum_exception(order_id, placed, amount_tolerance)
        if exception is not None:
            sum_exceptions.append(exception)

    return ObligationBuildResult(obligations=obligations, order_sum_exceptions=sum_exceptions)
