"""LangGraph assembly.

Builds the reconciliation state machine. Dependencies are bound into each node
with ``functools.partial`` so nodes receive only the state at call time. There is
one conditional edge: fuzzy matching runs only when it is enabled *and* there are
unmatched rows on both sides.

```mermaid
flowchart TD
    reconcile --> route{unmatched both sides and fuzzy on?}
    route -- yes --> fuzzy --> classify
    route -- no --> classify
    classify --> decide --> dispatch --> verify --> END
```
"""

from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import END, StateGraph

from reconcile.agent.nodes import (
    classify_node,
    decide_node,
    dispatch_node,
    fuzzy_node,
    reconcile_node,
    verify_node,
)
from reconcile.agent.state import AgentDependencies, ReconciliationState


def _route_after_reconcile(state: ReconciliationState, *, deps: AgentDependencies) -> str:
    """Run fuzzy matching only when enabled and both sides have leftovers."""
    if deps.fuzzy_enabled and state["unmatched_obligations"] and state["unmatched_settlements"]:
        return "fuzzy"
    return "classify"


def build_graph(deps: AgentDependencies) -> Any:
    """Build and compile the reconciliation graph for the given dependencies."""
    graph = StateGraph(ReconciliationState)

    graph.add_node("reconcile", partial(reconcile_node, deps=deps))
    graph.add_node("fuzzy", partial(fuzzy_node, deps=deps))
    graph.add_node("classify", partial(classify_node, deps=deps))
    graph.add_node("decide", partial(decide_node, deps=deps))
    graph.add_node("dispatch", partial(dispatch_node, deps=deps))
    graph.add_node("verify", partial(verify_node, deps=deps))

    graph.set_entry_point("reconcile")
    graph.add_conditional_edges(
        "reconcile",
        partial(_route_after_reconcile, deps=deps),
        {"fuzzy": "fuzzy", "classify": "classify"},
    )
    graph.add_edge("fuzzy", "classify")
    graph.add_edge("classify", "decide")
    graph.add_edge("decide", "dispatch")
    graph.add_edge("dispatch", "verify")
    graph.add_edge("verify", END)

    return graph.compile()
