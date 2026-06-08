"""LangGraph node functions.

Each node takes the shared state plus the injected :class:`AgentDependencies`
(bound via ``functools.partial`` in :mod:`reconcile.agent.graph`) and returns a
partial state update. Every node writes audit events, so the audit trail mirrors
the agent's reasoning step by step.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from reconcile.agent.planner import plan_action
from reconcile.agent.schemas import EmailMessageView, ExceptionDecision
from reconcile.agent.state import AgentDependencies, ReconciliationState
from reconcile.agent.verifier import mark_resolved
from reconcile.audit.repository import AuditRepository
from reconcile.logging_setup import get_logger
from reconcile.models.domain import (
    ExceptionReason,
    ExceptionRecord,
    MatchedPair,
    NotificationStatus,
    ObligationStatus,
    PlannerAction,
    RecipientRole,
    SlaStatus,
    make_mismatch_key,
)
from reconcile.notifications.base import SendResult
from reconcile.reconciliation import classify_leftovers, reconcile_keys, resolve_targets
from reconcile.reconciliation.rules import RecipientTarget

_log = get_logger("agent.nodes")


# --------------------------------------------------------------------------- #
# Node: deterministic key matching
# --------------------------------------------------------------------------- #


def reconcile_node(state: ReconciliationState, *, deps: AgentDependencies) -> dict[str, Any]:
    obligations = state["obligations"]
    settlements = state["settlements"]
    result = reconcile_keys(
        obligations,
        settlements,
        amount_tolerance=deps.config.reconciliation.amount_tolerance,
    )
    exceptions = list(state.get("order_sum_exceptions", [])) + result.exceptions

    with deps.session_factory() as session:
        AuditRepository(session).log_event(
            state["run_id"],
            "reconcile_completed",
            status="ok",
            details={
                "matched": len(result.matched),
                "key_exceptions": len(result.exceptions),
                "unmatched_obligations": len(result.unmatched_obligations),
                "unmatched_settlements": len(result.unmatched_settlements),
            },
        )
        session.commit()

    return {
        "matched": result.matched,
        "exceptions": exceptions,
        "unmatched_obligations": result.unmatched_obligations,
        "unmatched_settlements": result.unmatched_settlements,
        "fuzzy_auto_applied": [],
    }


# --------------------------------------------------------------------------- #
# Node: LLM fuzzy matching of leftovers
# --------------------------------------------------------------------------- #


def fuzzy_node(state: ReconciliationState, *, deps: AgentDependencies) -> dict[str, Any]:
    obligations = list(state["unmatched_obligations"])
    settlements = list(state["unmatched_settlements"])

    # Fuzzy matching is an optional enhancement: if the LLM call fails, degrade
    # gracefully to "no pairings" rather than failing the whole reconciliation.
    try:
        proposal = deps.llm.propose_fuzzy(obligations, settlements)
        pairings = proposal.pairings
    except Exception as exc:  # any LLM/provider error here is non-fatal
        _log.warning("fuzzy_match_skipped", error=str(exc))
        with deps.session_factory() as session:
            AuditRepository(session).log_event(
                state["run_id"],
                "fuzzy_match_skipped",
                status="degraded",
                details={"error": str(exc)},
            )
            session.commit()
        pairings = []

    auto_threshold = deps.config.fuzzy_match.auto_apply_threshold
    review_threshold = deps.config.fuzzy_match.review_threshold

    obl_by_order = {o.order_id: o for o in obligations}
    settle_by_id = {s.settlement_id: s for s in settlements}

    matched = list(state["matched"])
    exceptions = list(state["exceptions"])
    auto_applied = []
    events: list[tuple[str, str | None, str]] = []

    for pairing in sorted(pairings, key=lambda p: p.confidence, reverse=True):
        # Skip placeholder rows the model may emit for unmatchable orders.
        if pairing.order_id is None or pairing.settlement_id is None:
            continue
        obligation = obl_by_order.get(pairing.order_id)
        settlement = settle_by_id.get(pairing.settlement_id)
        if obligation is None or settlement is None:
            continue  # already consumed by a higher-confidence pairing

        if pairing.confidence >= auto_threshold:
            matched.append(MatchedPair(obligation=obligation, settlement=settlement))
            auto_applied.append(pairing)
            events.append(("fuzzy_auto_applied", obligation.order_id, pairing.rationale))
        elif pairing.confidence >= review_threshold:
            exceptions.append(_fuzzy_review_exception(obligation, settlement, pairing.rationale))
            events.append(("fuzzy_review_flagged", obligation.order_id, pairing.rationale))
        else:
            continue

        del obl_by_order[pairing.order_id]
        del settle_by_id[pairing.settlement_id]

    with deps.session_factory() as session:
        repo = AuditRepository(session)
        for event_type, order_id, detail in events:
            repo.log_event(
                state["run_id"], event_type, order_id=order_id, details={"rationale": detail}
            )
        session.commit()

    return {
        "matched": matched,
        "exceptions": exceptions,
        "unmatched_obligations": list(obl_by_order.values()),
        "unmatched_settlements": list(settle_by_id.values()),
        "fuzzy_auto_applied": auto_applied,
    }


def _fuzzy_review_exception(obligation: Any, settlement: Any, rationale: str) -> ExceptionRecord:
    return ExceptionRecord(
        reason=ExceptionReason.FUZZY_MATCH_REVIEW,
        status=ObligationStatus.UNMATCHED,
        order_id=obligation.order_id,
        settlement_id=settlement.settlement_id,
        payment_type=obligation.payment_type,
        store_id=obligation.store_id,
        payment_gateway=obligation.payment_gateway,
        expected_amount=obligation.expected_amount,
        actual_amount=settlement.amount,
        detail=f"Possible match (needs review): {rationale}",
    )


# --------------------------------------------------------------------------- #
# Node: classify remaining leftovers
# --------------------------------------------------------------------------- #


def classify_node(state: ReconciliationState, *, deps: AgentDependencies) -> dict[str, Any]:
    leftovers = classify_leftovers(
        state["unmatched_obligations"],
        state["unmatched_settlements"],
        grace_days=deps.config.reconciliation.sla_grace_days,
        as_of_date=state["as_of_date"],
    )
    exceptions = list(state["exceptions"]) + leftovers

    with deps.session_factory() as session:
        AuditRepository(session).log_event(
            state["run_id"],
            "exceptions_finalized",
            status="ok",
            details={"total_exceptions": len(exceptions)},
        )
        session.commit()

    return {"exceptions": exceptions}


# --------------------------------------------------------------------------- #
# Node: LLM decision + planner validation per exception
# --------------------------------------------------------------------------- #


def decide_node(state: ReconciliationState, *, deps: AgentDependencies) -> dict[str, Any]:
    threshold = deps.config.reconciliation.high_value_threshold
    decisions: list[ExceptionDecision] = []

    with deps.session_factory() as session:
        repo = AuditRepository(session)
        for exception in state["exceptions"]:
            within_sla = exception.sla_status is SlaStatus.WITHIN_SLA
            proposed = deps.llm.decide(
                exception, within_sla=within_sla, high_value_threshold=threshold
            )
            planned = plan_action(
                proposed, planner_config=deps.config.planner, within_sla=within_sla
            )
            final = ExceptionDecision(
                severity=proposed.severity,
                action=planned.action,
                rationale=proposed.rationale,
            )
            decisions.append(final)
            repo.log_event(
                state["run_id"],
                "exception_decided",
                order_id=exception.order_id,
                action=final.action.value,
                reason=exception.reason.value,
                status=final.severity.value,
                details={"used_fallback": planned.used_fallback, "rationale": final.rationale},
            )
        session.commit()

    return {"decisions": decisions}


# --------------------------------------------------------------------------- #
# Node: dispatch notifications per decision
# --------------------------------------------------------------------------- #


def dispatch_node(state: ReconciliationState, *, deps: AgentDependencies) -> dict[str, Any]:
    dry_run = state.get("dry_run", False)
    run_id = state["run_id"]

    emails: list[EmailMessageView] = []
    current_keys: list[str] = []
    lifecycle: list[tuple[str, str, str]] = []
    events: list[dict[str, Any]] = []

    for exception, decision in zip(state["exceptions"], state["decisions"], strict=True):
        if decision.action is PlannerAction.WAIT:
            for target in resolve_targets(exception, deps.config):
                lifecycle.append((target.mismatch_key, exception.reason.value, "OPEN"))
                current_keys.append(target.mismatch_key)
            events.append(_event(exception, decision.action, "WAITING"))
            continue

        tag, status, targets = _targets_for_action(exception, decision.action, deps)
        for target in targets:
            draft = deps.llm.draft_email(exception, target.role, tag)
            result = _dispatch_one(deps, run_id, target, draft.subject, draft.body, dry_run=dry_run)
            emails.append(
                EmailMessageView(
                    recipient_role=target.role.value,
                    recipient_email=target.email,
                    subject=draft.subject,
                    body=draft.body,
                    status=result.status.value,
                    reason=exception.reason.value,
                    mismatch_key=target.mismatch_key,
                )
            )
            lifecycle.append((target.mismatch_key, exception.reason.value, status))
            current_keys.append(target.mismatch_key)
            events.append(_event(exception, decision.action, result.status.value))

    with deps.session_factory() as session:
        repo = AuditRepository(session)
        for key, reason, life_status in lifecycle:
            repo.upsert_exception(
                mismatch_key=key, run_id=run_id, reason=reason, status=life_status
            )
        for event in events:
            repo.log_event(run_id, "notification_dispatched", **event)
        session.commit()

    return {"emails": emails, "current_keys": current_keys}


def _event(exception: ExceptionRecord, action: PlannerAction, status: str) -> dict[str, Any]:
    return {
        "order_id": exception.order_id,
        "action": action.value,
        "reason": exception.reason.value,
        "status": status,
    }


def _targets_for_action(
    exception: ExceptionRecord, action: PlannerAction, deps: AgentDependencies
) -> tuple[str, str, list[RecipientTarget]]:
    if action is PlannerAction.ESCALATE:
        key = make_mismatch_key(
            exception.reason,
            exception.order_id,
            exception.settlement_id,
            exception.payment_type,
            RecipientRole.ADMIN,
        )
        admin = RecipientTarget(
            role=RecipientRole.ADMIN,
            email=deps.config.recipients.admin,
            mismatch_key=key,
        )
        return "escalate", "ESCALATED", [admin]

    targets = resolve_targets(exception, deps.config)
    if action is PlannerAction.REQUEST_RECHECK:
        return "recheck", "AWAITING_RECHECK", targets
    return "email", "OPEN", targets


def _dispatch_one(
    deps: AgentDependencies,
    run_id: str,
    target: RecipientTarget,
    subject: str,
    body: str,
    *,
    dry_run: bool,
) -> SendResult:
    if dry_run:
        return SendResult(status=NotificationStatus.SKIPPED, reason="dry_run")
    return deps.notifications.dispatch(
        run_id=run_id,
        mismatch_key=target.mismatch_key,
        recipient_role=target.role,
        recipient_email=target.email,
        subject=subject,
        body=body,
    )


# --------------------------------------------------------------------------- #
# Node: verify and summarize
# --------------------------------------------------------------------------- #


def verify_node(state: ReconciliationState, *, deps: AgentDependencies) -> dict[str, Any]:
    run_id = state["run_id"]
    current_keys = set(state.get("current_keys", []))

    with deps.session_factory() as session:
        resolved = mark_resolved(session, run_id=run_id, current_keys=current_keys)
        AuditRepository(session).log_event(
            run_id, "verify_completed", status="ok", details={"resolved": resolved}
        )
        session.commit()

    summary = _build_summary(state, resolved)
    return {"summary": summary}


def _build_summary(state: ReconciliationState, resolved: int) -> dict[str, Any]:
    exceptions = state.get("exceptions", [])
    decisions = state.get("decisions", [])
    emails = state.get("emails", [])

    reason_counts = Counter(exc.reason.value for exc in exceptions)
    action_counts = Counter(dec.action.value for dec in decisions)
    notification_counts = Counter(email.status for email in emails)

    return {
        "matched": len(state.get("matched", [])),
        "exceptions_total": len(exceptions),
        "exceptions_by_reason": dict(reason_counts),
        "actions": dict(action_counts),
        "notifications": dict(notification_counts),
        "fuzzy_auto_applied": len(state.get("fuzzy_auto_applied", [])),
        "resolved": resolved,
    }
