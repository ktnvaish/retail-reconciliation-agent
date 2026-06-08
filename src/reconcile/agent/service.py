"""Agent orchestration.

`ReconciliationAgent.run` owns the run lifecycle: it builds obligations, opens a
run-scoped log context, starts/finishes the run record, invokes the graph, and
turns the final state into a :class:`RunOutcome`. Any unhandled failure inside
the graph is converted into an incident (never a silent crash).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from reconcile.agent.graph import build_graph
from reconcile.agent.llm import build_llm_client
from reconcile.agent.schemas import EmailMessageView, ExceptionView
from reconcile.agent.state import AgentDependencies, ReconciliationState
from reconcile.audit.repository import AuditRepository
from reconcile.config import AppConfig, AppSettings
from reconcile.incidents.models import FailureType
from reconcile.incidents.service import IncidentService
from reconcile.incidents.store import IncidentStore
from reconcile.logging_setup import get_logger, new_run_id, run_context
from reconcile.models.domain import ExceptionRecord, Order, Settlement
from reconcile.notifications.service import build_notification_service
from reconcile.reconciliation import build_obligations

_log = get_logger("agent")


class RunOutcome(BaseModel):
    """The result of a reconciliation run, suitable for the API/UI/CLI."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str
    orders_count: int
    settlements_count: int
    summary: dict[str, Any] = Field(default_factory=dict)
    emails: list[EmailMessageView] = Field(default_factory=list)
    exceptions: list[ExceptionView] = Field(default_factory=list)
    fuzzy_auto_applied: int = 0
    incident_id: str | None = None


class ReconciliationAgent:
    """Runs the compiled reconciliation graph and manages the run lifecycle."""

    def __init__(self, deps: AgentDependencies) -> None:
        self._deps = deps
        self._graph = build_graph(deps)

    def run(
        self,
        *,
        orders: list[Order],
        settlements: list[Settlement],
        run_id: str | None = None,
        as_of_date: date | None = None,
        input_hash: str | None = None,
        dry_run: bool = False,
    ) -> RunOutcome:
        deps = self._deps
        rid = run_id or new_run_id()
        as_of = as_of_date or date.today()

        with run_context(rid):
            built = build_obligations(
                orders, amount_tolerance=deps.config.reconciliation.amount_tolerance
            )
            self._start_run(rid, input_hash, len(orders), len(settlements))

            initial: ReconciliationState = {
                "run_id": rid,
                "as_of_date": as_of,
                "dry_run": dry_run,
                "obligations": built.obligations,
                "settlements": settlements,
                "order_sum_exceptions": built.order_sum_exceptions,
                "matched": [],
                "exceptions": [],
                "unmatched_obligations": [],
                "unmatched_settlements": [],
                "decisions": [],
                "emails": [],
                "current_keys": [],
            }

            try:
                final: dict[str, Any] = dict(self._graph.invoke(initial))
            except Exception as exc:  # convert any graph failure into an incident
                return self._handle_failure(rid, exc, len(orders), len(settlements))

            summary = final.get("summary", {})
            self._finish_run(rid, "completed", summary)
            return self._build_outcome(rid, "completed", len(orders), len(settlements), final)

    # -- lifecycle helpers ------------------------------------------------- #

    def _start_run(
        self, run_id: str, input_hash: str | None, orders_count: int, settlements_count: int
    ) -> None:
        with self._deps.session_factory() as session:
            AuditRepository(session).start_run(
                run_id,
                input_hash=input_hash,
                orders_count=orders_count,
                settlements_count=settlements_count,
            )
            session.commit()

    def _finish_run(self, run_id: str, status: str, summary: dict[str, Any]) -> None:
        with self._deps.session_factory() as session:
            AuditRepository(session).finish_run(run_id, status=status, summary=summary)
            session.commit()

    def _handle_failure(
        self, run_id: str, exc: Exception, orders_count: int, settlements_count: int
    ) -> RunOutcome:
        _log.error("agent_run_failed", run_id=run_id, error=str(exc))
        incident = self._deps.incidents.raise_incident(
            run_id=run_id,
            failure_type=FailureType.PLANNER_ERROR,
            root_cause=str(exc),
            remediation="Inspect the run's audit log and inputs; re-run after fixing.",
        )
        self._finish_run(run_id, "failed", {"error": str(exc), "incident": incident.incident_id})
        return RunOutcome(
            run_id=run_id,
            status="failed",
            orders_count=orders_count,
            settlements_count=settlements_count,
            incident_id=incident.incident_id,
        )

    def _build_outcome(
        self,
        run_id: str,
        status: str,
        orders_count: int,
        settlements_count: int,
        final: dict[str, Any],
    ) -> RunOutcome:
        exceptions: list[ExceptionRecord] = final.get("exceptions", [])
        decisions = final.get("decisions", [])
        views = [_exception_view(exc, dec) for exc, dec in zip(exceptions, decisions, strict=False)]
        return RunOutcome(
            run_id=run_id,
            status=status,
            orders_count=orders_count,
            settlements_count=settlements_count,
            summary=final.get("summary", {}),
            emails=final.get("emails", []),
            exceptions=views,
            fuzzy_auto_applied=len(final.get("fuzzy_auto_applied", [])),
        )


def _exception_view(exception: ExceptionRecord, decision: Any) -> ExceptionView:
    return ExceptionView(
        reason=exception.reason.value,
        status=exception.status.value,
        order_id=exception.order_id,
        settlement_id=exception.settlement_id,
        payment_type=exception.payment_type.value if exception.payment_type else None,
        expected_amount=str(exception.expected_amount)
        if exception.expected_amount is not None
        else None,
        actual_amount=str(exception.actual_amount) if exception.actual_amount is not None else None,
        sla_status=exception.sla_status.value,
        severity=decision.severity.value,
        action=decision.action.value,
        rationale=decision.rationale,
    )


def build_agent(
    settings: AppSettings,
    config: AppConfig,
    session_factory: Callable[[], Session],
) -> ReconciliationAgent:
    """Wire a fully configured reconciliation agent."""
    return ReconciliationAgent(build_dependencies(settings, config, session_factory))


def build_dependencies(
    settings: AppSettings,
    config: AppConfig,
    session_factory: Callable[[], Session],
) -> AgentDependencies:
    """Wire the agent's dependencies (also reused by the API for telemetry)."""
    notifications = build_notification_service(settings, config.resilience, session_factory)
    incidents = IncidentService(
        store=IncidentStore(settings.incidents_dir),
        admin_email=config.recipients.admin,
        notification_service=notifications,
        best_effort_email=config.incidents.admin_email_best_effort,
    )
    return AgentDependencies(
        config=config,
        llm=build_llm_client(settings),
        notifications=notifications,
        incidents=incidents,
        session_factory=session_factory,
        fuzzy_enabled=config.fuzzy_match.enabled,
    )
