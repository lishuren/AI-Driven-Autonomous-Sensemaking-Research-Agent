"""Scout node for the sensemaking LangGraph workflow.

The Scout node is the acquisition entry point.  It calls the ScoutTool
pipeline for the current query and appends normalized documents to state.
It also increments ``iteration_count`` so the router can guard against
infinite loops.

The node knows nothing about entities, triplets, contradictions, or routing.
Its only job is to acquire documents and advance the iteration counter.
"""

from __future__ import annotations

import logging
from typing import Any

from ..state import ResearchState
from ..tools.scout_tool import ScoutTool

logger = logging.getLogger(__name__)


def make_scout_node(scout_tool: ScoutTool | None = None):
    """Return a Scout node callable closed over *scout_tool*.

    Parameters
    ----------
    scout_tool:
        Pre-configured ScoutTool.  A default instance is created when omitted.
    """
    _scout = scout_tool or ScoutTool()

    async def scout_node(state: ResearchState) -> dict[str, Any]:
        query = state.get("current_query", "").strip()
        new_iteration = state.get("iteration_count", 0) + 1

        if not query:
            logger.warning(
                "Scout node (iteration %d): empty query — skipping acquisition.",
                new_iteration,
            )
            return {"iteration_count": new_iteration}

        docs = await _scout.acquire(query)
        doc_dicts = [doc.model_dump(mode="json") for doc in docs]
        logger.info(
            "Scout node (iteration %d): acquired %d documents for query %r.",
            new_iteration,
            len(doc_dicts),
            query,
        )

        # Returning a list for 'documents' extends the existing list via
        # operator.add (the Annotated reducer declared in ResearchState).
        return {
            "documents": doc_dicts,
            "iteration_count": new_iteration,
        }

    return scout_node
