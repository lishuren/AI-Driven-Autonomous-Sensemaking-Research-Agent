"""Writer node (stub) for the sensemaking LangGraph workflow.

The Writer will synthesize a final narrative from the knowledge graph and
contradiction log.  This initial stub stores a minimal placeholder so the
workflow can terminate cleanly.

Full Writer responsibilities (to be implemented):
- generate the final narrative from graph structure, not raw snippets alone
- include disputed facts and strategic gaps
- make the report traceable to triplets and evidence
- produce structured output that matches the report-spec contract
"""

from __future__ import annotations

import logging
from typing import Any

from ..state import ResearchState

logger = logging.getLogger(__name__)


async def writer_node(state: ResearchState) -> dict[str, Any]:
    """Stub Writer node.  Stores a minimal placeholder synthesis."""
    entity_count = len(state.get("entities", {}))
    triplet_count = len(state.get("triplets", []))
    doc_count = len(state.get("documents", []))
    contradiction_count = len(state.get("contradictions", []))
    query = state.get("current_query", "")

    placeholder = (
        f"[Writer stub] Research on '{query}' completed.\n"
        f"Collected {doc_count} documents, {entity_count} entities, "
        f"{triplet_count} triplets, {contradiction_count} contradictions.\n"
        f"Full synthesis not yet implemented."
    )

    logger.info(
        "Writer node (stub): synthesizing placeholder for query %r.", query
    )

    return {"final_synthesis": placeholder}
