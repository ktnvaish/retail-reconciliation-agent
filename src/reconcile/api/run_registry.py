"""In-memory registry of background reconciliation runs.

Because a run is now executed off the request thread, its
:class:`~reconcile.agent.service.RunOutcome` has to be stashed somewhere the
later ``/results/{run_id}`` request can pick it up. A small thread-safe,
LRU-bounded dict on the app context is sufficient for the single-replica demo.

This is deliberately *not* durable: a process restart loses in-flight results
(the run itself is still recorded in SQLite). Persisting the full outcome to the
database is the documented next step for a multi-replica deployment.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

from reconcile.agent.service import RunOutcome

RunState = Literal["unknown", "pending", "done", "error"]


@dataclass
class RunRecord:
    """Tracking record for one background run."""

    demo: bool = False
    outcome: RunOutcome | None = None
    error: str | None = None

    @property
    def state(self) -> RunState:
        if self.error is not None:
            return "error"
        if self.outcome is not None:
            return "done"
        return "pending"


class RunRegistry:
    """Thread-safe, LRU-bounded store of background run results."""

    def __init__(self, max_entries: int = 200) -> None:
        self._lock = threading.Lock()
        self._runs: OrderedDict[str, RunRecord] = OrderedDict()
        self._max_entries = max_entries

    def start(self, run_id: str, *, demo: bool = False) -> None:
        """Register a run as pending before its background thread is launched."""
        with self._lock:
            self._runs[run_id] = RunRecord(demo=demo)
            self._evict_locked()

    def set_outcome(self, run_id: str, outcome: RunOutcome) -> None:
        with self._lock:
            record = self._runs.get(run_id) or RunRecord()
            record.outcome = outcome
            self._runs[run_id] = record
            self._runs.move_to_end(run_id)

    def set_error(self, run_id: str, message: str) -> None:
        with self._lock:
            record = self._runs.get(run_id) or RunRecord()
            record.error = message
            self._runs[run_id] = record
            self._runs.move_to_end(run_id)

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def state(self, run_id: str) -> RunState:
        record = self.get(run_id)
        return record.state if record is not None else "unknown"

    def _evict_locked(self) -> None:
        while len(self._runs) > self._max_entries:
            self._runs.popitem(last=False)
