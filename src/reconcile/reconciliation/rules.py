"""Routing rules: map an exception to the stakeholders who should be notified.

Each :class:`~reconcile.models.domain.ExceptionReason` has a default set of
recipient roles. When an order row carries an explicit ``responsible_party``,
that override replaces the default routing for its exceptions. For each resolved
target this module also computes the stable ``mismatch_key`` used for
idempotency.
"""

from __future__ import annotations

from dataclasses import dataclass

from reconcile.config import AppConfig
from reconcile.models.domain import (
    ExceptionReason,
    ExceptionRecord,
    RecipientRole,
    make_mismatch_key,
)


@dataclass(frozen=True)
class RecipientTarget:
    """A resolved notification target for one exception."""

    role: RecipientRole
    email: str
    mismatch_key: str


# Default recipient role(s) per reason (see PRD §7.5a).
DEFAULT_ROUTING: dict[ExceptionReason, tuple[RecipientRole, ...]] = {
    ExceptionReason.CASH_MISSING: (RecipientRole.STORE_MANAGER,),
    ExceptionReason.ONLINE_MISSING: (RecipientRole.PAYMENT_GATEWAY,),
    ExceptionReason.LATE_SETTLEMENT: (RecipientRole.PAYMENT_GATEWAY,),
    ExceptionReason.AMOUNT_SHORT: (RecipientRole.PAYMENT_GATEWAY, RecipientRole.STORE_MANAGER),
    ExceptionReason.AMOUNT_EXCESS: (RecipientRole.PAYMENT_GATEWAY, RecipientRole.STORE_MANAGER),
    ExceptionReason.DUPLICATE_SETTLEMENT: (RecipientRole.PAYMENT_GATEWAY, RecipientRole.BANK),
    ExceptionReason.UNMATCHED_SETTLEMENT: (RecipientRole.BANK, RecipientRole.PAYMENT_GATEWAY),
    ExceptionReason.ORDER_SUM_MISMATCH: (RecipientRole.STORE_MANAGER,),
    ExceptionReason.FUZZY_MATCH_REVIEW: (RecipientRole.ADMIN,),
}


def default_roles(reason: ExceptionReason) -> tuple[RecipientRole, ...]:
    """Default recipient roles for a reason."""
    return DEFAULT_ROUTING[reason]


def resolve_targets(exception: ExceptionRecord, config: AppConfig) -> list[RecipientTarget]:
    """Resolve the notification targets for an exception.

    A non-null ``responsible_party`` on the exception overrides the default
    routing. Duplicate roles are collapsed; ordering is preserved.
    """
    if exception.responsible_party is not None:
        roles: tuple[RecipientRole, ...] = (exception.responsible_party,)
    else:
        roles = default_roles(exception.reason)

    targets: list[RecipientTarget] = []
    seen: set[RecipientRole] = set()
    for role in roles:
        if role in seen:
            continue
        seen.add(role)
        email = config.recipients.for_role(role, exception.payment_gateway)
        key = make_mismatch_key(
            exception.reason,
            exception.order_id,
            exception.settlement_id,
            exception.payment_type,
            role,
        )
        targets.append(RecipientTarget(role=role, email=email, mismatch_key=key))
    return targets
