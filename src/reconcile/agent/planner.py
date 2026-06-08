"""Planner: validate the LLM's chosen action against the allow-list.

The LLM proposes an action; the planner enforces the guardrails:

* the action must be in the configured allow-list, and
* ``WAIT`` is only valid while the obligation is within its SLA grace window.

Any violation falls back deterministically to the configured action (default
``ESCALATE``), and the fallback is flagged so it can be audited — never a silent
override.
"""

from __future__ import annotations

from dataclasses import dataclass

from reconcile.agent.schemas import ExceptionDecision
from reconcile.config import PlannerConfig
from reconcile.models.domain import PlannerAction


@dataclass(frozen=True)
class PlannedAction:
    """The validated action plus whether a fallback was applied."""

    action: PlannerAction
    used_fallback: bool


def plan_action(
    decision: ExceptionDecision,
    *,
    planner_config: PlannerConfig,
    within_sla: bool,
) -> PlannedAction:
    """Validate ``decision.action`` and return the action the agent will execute."""
    allowed = set(planner_config.allowed_actions)
    fallback = planner_config.off_list_fallback

    action = decision.action
    if action not in allowed:
        return PlannedAction(action=fallback, used_fallback=True)
    if action is PlannerAction.WAIT and not within_sla:
        # WAIT is only valid within the SLA grace window.
        return PlannedAction(action=fallback, used_fallback=True)
    return PlannedAction(action=action, used_fallback=False)
