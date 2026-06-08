"""Deterministic reconciliation core.

Public API:

* :func:`build_obligations` — explode order rows into obligations + sum checks.
* :func:`reconcile` — full deterministic reconciliation (no fuzzy matching).
* :func:`reconcile_keys` / :func:`classify_leftovers` — the two halves the agent
  uses so it can interpose fuzzy matching.
* :func:`resolve_targets` — route an exception to recipient targets.
"""

from reconcile.reconciliation.matcher import (
    KeyMatchResult,
    ReconciliationResult,
    classify_leftovers,
    reconcile,
    reconcile_keys,
)
from reconcile.reconciliation.obligations import ObligationBuildResult, build_obligations
from reconcile.reconciliation.rules import RecipientTarget, default_roles, resolve_targets
from reconcile.reconciliation.sla import compute_age_days, sla_status

__all__ = [
    "KeyMatchResult",
    "ObligationBuildResult",
    "RecipientTarget",
    "ReconciliationResult",
    "build_obligations",
    "classify_leftovers",
    "compute_age_days",
    "default_roles",
    "reconcile",
    "reconcile_keys",
    "resolve_targets",
    "sla_status",
]
