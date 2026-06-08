"""Progress reporting for in-flight background runs.

The agent already writes one typed audit event per pipeline phase, so we can
derive live progress for the UI without adding any new instrumentation — the
audit trail doubles as the progress feed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from reconcile.audit.repository import AuditRepository

if TYPE_CHECKING:
    from reconcile.app import AppContext

# Rank of each audit event in pipeline order. The highest rank seen for a run is
# the phase it has reached.
_EVENT_RANK: dict[str, int] = {
    "reconcile_completed": 1,
    "fuzzy_auto_applied": 2,
    "fuzzy_review_flagged": 2,
    "fuzzy_match_skipped": 2,
    "exceptions_finalized": 3,
    "exception_decided": 4,
    "notification_dispatched": 5,
    "verify_completed": 6,
}
_TOTAL_RANK = 6

_PHASE_LABEL: dict[int, str] = {
    0: "Parsing and matching orders to settlements…",
    1: "Matching complete — checking for leftovers…",
    2: "Fuzzy-matching residual rows…",
    3: "Reviewing exceptions…",
    4: "Deciding the next action per exception…",
    5: "Sending notifications…",
    6: "Finalizing and writing the audit trail…",
}


def compute_progress(context: AppContext, run_id: str) -> dict[str, Any] | None:
    """Return a progress snapshot for ``run_id``, or ``None`` if unknown."""
    registry = context.run_registry
    state = registry.state(run_id)

    if state == "unknown":
        return None
    if state in ("done", "error"):
        return {
            "status": "completed" if state == "done" else "failed",
            "percent": 100,
            "label": "Done." if state == "done" else "Run failed.",
            "done": True,
            "redirect": f"/results/{run_id}",
        }

    # Pending: derive the current phase from the audit events written so far.
    with context.session_factory() as session:
        repo = AuditRepository(session)
        run = repo.get_run(run_id)
        events = repo.list_events(run_id) if run is not None else []

    ranks = [rank for event in events if (rank := _EVENT_RANK.get(event.event_type)) is not None]
    rank = max(ranks, default=0)
    label = _PHASE_LABEL[rank]

    if rank == 5:
        dispatched = sum(1 for e in events if e.event_type == "notification_dispatched")
        if dispatched:
            label = f"Sending notifications ({dispatched} processed)…"

    percent = max(3, round(rank / _TOTAL_RANK * 90))
    return {"status": "running", "percent": percent, "label": label, "done": False}
