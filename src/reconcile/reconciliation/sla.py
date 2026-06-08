"""SLA evaluation for obligations.

The matcher is SLA-blind; this module is consulted only to decide whether an
*unmatched online* obligation is still within its settlement grace window (the
planner may then ``WAIT``) or has breached it (and should be escalated by email).
Cash obligations have no gateway-settlement SLA and are reported as ``NA``.
"""

from __future__ import annotations

from datetime import date

from reconcile.models.domain import Obligation, PaymentType, SlaStatus


def compute_age_days(order_date: date, as_of_date: date) -> int:
    """Whole days between the order date and the evaluation date."""
    return (as_of_date - order_date).days


def sla_status(
    obligation: Obligation,
    as_of_date: date,
    grace_days: dict[PaymentType, int],
) -> tuple[SlaStatus, int]:
    """Return ``(status, age_days)`` for an obligation as of ``as_of_date``."""
    age = compute_age_days(obligation.order_date, as_of_date)

    if not obligation.payment_type.is_online:
        return SlaStatus.NA, age

    grace = grace_days.get(obligation.payment_type)
    if grace is None:
        return SlaStatus.NA, age

    status = SlaStatus.WITHIN_SLA if age <= grace else SlaStatus.BREACHED
    return status, age
