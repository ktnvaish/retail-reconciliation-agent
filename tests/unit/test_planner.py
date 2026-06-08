"""Tests for the planner's allow-list validation and fallbacks."""

from __future__ import annotations

import pytest

from reconcile.agent.planner import plan_action
from reconcile.agent.schemas import ExceptionDecision, Severity
from reconcile.config import PlannerConfig
from reconcile.models.domain import PlannerAction

pytestmark = pytest.mark.unit

PLANNER = PlannerConfig(
    allowed_actions=[
        PlannerAction.WAIT,
        PlannerAction.EMAIL_PG,
        PlannerAction.EMAIL_STORE_MANAGER,
        PlannerAction.ESCALATE,
    ],
    off_list_fallback=PlannerAction.ESCALATE,
)


def _decision(action: PlannerAction) -> ExceptionDecision:
    return ExceptionDecision(severity=Severity.ROUTINE, action=action, rationale="x")


def test_allowed_action_passes_through() -> None:
    planned = plan_action(
        _decision(PlannerAction.EMAIL_PG), planner_config=PLANNER, within_sla=False
    )
    assert planned.action is PlannerAction.EMAIL_PG
    assert not planned.used_fallback


def test_off_list_action_falls_back() -> None:
    planned = plan_action(
        _decision(PlannerAction.REQUEST_RECHECK), planner_config=PLANNER, within_sla=False
    )
    assert planned.action is PlannerAction.ESCALATE
    assert planned.used_fallback


def test_wait_within_sla_is_allowed() -> None:
    planned = plan_action(_decision(PlannerAction.WAIT), planner_config=PLANNER, within_sla=True)
    assert planned.action is PlannerAction.WAIT
    assert not planned.used_fallback


def test_wait_outside_sla_falls_back() -> None:
    planned = plan_action(_decision(PlannerAction.WAIT), planner_config=PLANNER, within_sla=False)
    assert planned.action is PlannerAction.ESCALATE
    assert planned.used_fallback
