"""ReconcileFlow Agent.

An agentic retail payment reconciliation system: it reconciles an *orders* file
against a *settlements* file, uses an LLM to plan actions for exceptions, sends
email notifications to the right stakeholders, and records an auditable trail
with resilient, observable execution.

The matching/reconciliation path is fully deterministic; the LLM is used only
for planning, fuzzy-match proposals, message drafting, and explanations.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
