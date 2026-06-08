"""Prompt templates for the Groq LLM client.

Each builder returns a compact, explicit instruction plus the relevant facts.
The model is always asked for *structured* output (validated by Pydantic), so
prompts emphasize the allowed values and the decision criteria rather than free
text formatting.
"""

from __future__ import annotations

from reconcile.models.domain import ExceptionRecord, PlannerAction, RecipientRole

_SYSTEM = (
    "You are a meticulous finance-operations reconciliation assistant for an "
    "Indian retail business. You never invent numbers. You only choose from the "
    "actions you are given. Keep language clear and professional."
)

_ALLOWED_ACTIONS = ", ".join(a.value for a in PlannerAction)


def system_preamble() -> str:
    return _SYSTEM


def decide_prompt(
    exception: ExceptionRecord, *, within_sla: bool, high_value_threshold: str
) -> str:
    """Prompt the model to pick a severity and an allowed next action."""
    return (
        f"{_SYSTEM}\n\n"
        "Decide how to handle this reconciliation exception.\n"
        f"- reason: {exception.reason.value}\n"
        f"- status: {exception.status.value}\n"
        f"- payment_type: {exception.payment_type.value if exception.payment_type else 'n/a'}\n"
        f"- expected_amount: {exception.expected_amount}\n"
        f"- actual_amount: {exception.actual_amount}\n"
        f"- order_id: {exception.order_id}\n"
        f"- settlement_id: {exception.settlement_id}\n"
        f"- sla_status: {exception.sla_status.value}\n"
        f"- within_sla_grace: {within_sla}\n"
        f"- high_value_threshold: {high_value_threshold}\n\n"
        f"Choose action from: {_ALLOWED_ACTIONS}.\n"
        "Use WAIT only when the obligation is still within its SLA grace window. "
        "Use ESCALATE for ambiguous fuzzy-match reviews. Set severity to "
        "HIGH_VALUE when an amount meets or exceeds the high-value threshold."
    )


def fuzzy_prompt(obligations_text: str, settlements_text: str) -> str:
    """Prompt the model to propose pairings between unmatched rows."""
    return (
        f"{_SYSTEM}\n\n"
        "Some orders and settlements could not be matched by exact keys. Propose "
        "likely pairings ONLY when the amounts match and the dates/sources are "
        "plausibly related. Give each a confidence in [0,1] and a short rationale. "
        "Do not pair rows with different amounts.\n\n"
        f"UNMATCHED ORDERS:\n{obligations_text}\n\n"
        f"UNMATCHED SETTLEMENTS:\n{settlements_text}\n"
    )


def draft_prompt(exception: ExceptionRecord, role: RecipientRole, tag: str) -> str:
    """Prompt the model to draft a plain-text notification email."""
    intent = {
        "email": "notify the recipient and ask them to investigate",
        "recheck": "ask the recipient to re-verify and re-upload corrected data",
        "escalate": "escalate for manual review",
    }.get(tag, "notify the recipient")
    return (
        f"{_SYSTEM}\n\n"
        f"Write a concise plain-text email to the {role.value.replace('_', ' ').lower()} to {intent}.\n"
        "Include the key facts and a clear call to action. No HTML, no markdown.\n\n"
        f"- reason: {exception.reason.value}\n"
        f"- order_id: {exception.order_id}\n"
        f"- settlement_id: {exception.settlement_id}\n"
        f"- payment_type: {exception.payment_type.value if exception.payment_type else 'n/a'}\n"
        f"- expected_amount: {exception.expected_amount}\n"
        f"- actual_amount: {exception.actual_amount}\n"
        f"- detail: {exception.detail}\n"
    )
