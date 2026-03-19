"""Router node for the sensemaking LangGraph workflow.

Wraps the ``should_continue`` decision function from ``sensemaking_agent.graph``
and returns a LangGraph ``Command`` that both updates state (route_history) and
signals which node the workflow should transition to next.

The router does not mutate documents, entities, triplets, or contradictions.
Its only state mutation is appending to ``route_history``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from langgraph.types import Command

from ..graph import RouterConfig, apply_route_decision, should_continue
from ..state import ResearchState

logger = logging.getLogger(__name__)

# Maps RouteName string values to LangGraph node names declared in workflow.py.
_ROUTE_TO_NODE: dict[str, str] = {
    "continue_research": "scout",
    "resolve_conflict": "scout",
    "resolve_gap": "scout",
    "finalize": "writer",
}


def make_router_node(config: RouterConfig | None = None):
    """Return a Router node callable closed over *config*.

    Parameters
    ----------
    config:
        Router configuration controlling iteration limits and thresholds.
        A default ``RouterConfig`` is used when omitted.
    """
    _config = config or RouterConfig()

    def router_node(state: ResearchState) -> Command:
        decision = should_continue(state, _config)

        # Apply the route decision to produce the new state fragment.
        # apply_route_decision returns a full ResearchState but we only need
        # the mutated fields (current_query and route_history).
        updated = apply_route_decision(state, decision)

        # Stamp a timestamp on whatever route record was added.
        new_route_records: list[dict[str, Any]] = []
        if updated.get("route_history"):
            record = dict(updated["route_history"][-1])
            if "timestamp" not in record:
                record["timestamp"] = datetime.now(timezone.utc).isoformat()
            new_route_records.append(record)

        destination = _ROUTE_TO_NODE.get(str(decision.route), "writer")
        logger.info(
            "Router: iteration=%d route=%s reason=%r -> %s",
            state.get("iteration_count", 0),
            decision.route,
            decision.reason,
            destination,
        )

        update: dict[str, Any] = {
            "current_query": updated["current_query"],
        }
        if new_route_records:
            update["route_history"] = new_route_records

        return Command(goto=destination, update=update)

    return router_node
