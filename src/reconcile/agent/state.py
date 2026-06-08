"""Agent state and injected dependencies.

The LangGraph state (:class:`ReconciliationState`) carries *data only*. Runtime
collaborators (config, LLM, services, DB) are injected via
:class:`AgentDependencies` and bound into the node functions when the graph is
built, so nodes stay pure-ish and easy to test.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, TypedDict

from sqlalchemy.orm import Session

from reconcile.agent.llm import LLMClient
from reconcile.agent.schemas import EmailMessageView, ExceptionDecision, FuzzyPairing
from reconcile.config import AppConfig
from reconcile.incidents.service import IncidentService
from reconcile.models.domain import ExceptionRecord, MatchedPair, Obligation, Settlement
from reconcile.notifications.service import NotificationService


class ReconciliationState(TypedDict, total=False):
    """Mutable data passed between graph nodes."""

    run_id: str
    as_of_date: date
    dry_run: bool

    # Inputs (set before invocation).
    obligations: list[Obligation]
    settlements: list[Settlement]
    order_sum_exceptions: list[ExceptionRecord]

    # Reconciliation working set.
    matched: list[MatchedPair]
    key_exceptions: list[ExceptionRecord]
    unmatched_obligations: list[Obligation]
    unmatched_settlements: list[Settlement]
    fuzzy_auto_applied: list[FuzzyPairing]

    # Finalized exceptions and per-exception decisions (aligned lists).
    exceptions: list[ExceptionRecord]
    decisions: list[ExceptionDecision]

    # Outputs.
    emails: list[EmailMessageView]
    current_keys: list[str]
    summary: dict[str, Any]


@dataclass
class AgentDependencies:
    """Collaborators injected into the graph's nodes."""

    config: AppConfig
    llm: LLMClient
    notifications: NotificationService
    incidents: IncidentService
    session_factory: Callable[[], Session]
    fuzzy_enabled: bool = True
