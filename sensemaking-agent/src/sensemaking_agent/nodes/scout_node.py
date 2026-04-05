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
from pathlib import Path
from typing import Any

from ..state import ResearchState
from ..tools.scout_tool import ScoutTool
from ..tools.resource_loader import load_resources

logger = logging.getLogger(__name__)

_MAX_ENTITY_HINTS = 5

# Optional GraphRAG tool import.
_HAS_GRAPHRAG_TOOL = False
try:
    from ..tools.graphrag_tool import GraphRAGTool
    _HAS_GRAPHRAG_TOOL = True
except ImportError:
    pass


def _build_entity_hint(state: ResearchState) -> str:
    entities = state.get("entities") or {}
    if not entities:
        return ""

    local_doc_ids = {
        str(doc.get("document_id", ""))
        for doc in state.get("documents", [])
        if doc.get("source_type") == "local_resource"
    }
    if not local_doc_ids:
        return ""

    hinted_entities: list[str] = []
    for name, entity in entities.items():
        source_ids = {str(item) for item in entity.get("source_document_ids", [])}
        if source_ids & local_doc_ids:
            clean_name = str(name).strip()
            if clean_name:
                hinted_entities.append(clean_name)

    if not hinted_entities:
        return ""

    hinted_entities = sorted(set(hinted_entities), key=str.lower)[:_MAX_ENTITY_HINTS]
    return f" context from local resources: {'; '.join(hinted_entities)}"


def _build_constraint_hint(state: ResearchState) -> str:
    raw_constraints = str(state.get("constraints") or "").strip()
    if not raw_constraints:
        return ""

    compact = " ".join(line.strip("- *\t ") for line in raw_constraints.splitlines() if line.strip())
    if not compact:
        return ""
    return f" constraints: {compact}"


def _poll_new_resource_documents(state: ResearchState) -> tuple[list[dict[str, Any]], list[str]]:
    watched_dir = (state.get("watched_resources_dir") or "").strip()
    if not watched_dir:
        return [], []

    root = Path(watched_dir)
    if not root.is_dir():
        logger.warning("Scout node: watched resources directory missing: %s", watched_dir)
        return [], []

    seen = {Path(item).resolve().as_posix() for item in state.get("watched_resources_seen", [])}
    candidate_paths = sorted(
        path.resolve().as_posix()
        for path in root.rglob("*")
        if path.is_file()
    )
    unseen_paths = [path for path in candidate_paths if path not in seen]
    if not unseen_paths:
        return [], []

    loaded_docs = load_resources(watched_dir)
    new_docs: list[dict[str, Any]] = []
    for doc in loaded_docs:
        source_path = str((doc.metadata or {}).get("original_path", "")).strip()
        if not source_path:
            continue
        normalized_source_path = Path(source_path).resolve().as_posix()
        if normalized_source_path in unseen_paths:
            new_docs.append(doc.model_dump(mode="json"))

    return new_docs, unseen_paths


def make_scout_node(scout_tool: ScoutTool | None = None, graphrag_tool: Any = None):
    """Return a Scout node callable closed over *scout_tool*.

    Parameters
    ----------
    scout_tool:
        Pre-configured ScoutTool.  A default instance is created when omitted.
    graphrag_tool:
        Optional ``GraphRAGTool`` instance.  When provided, the Scout also
        queries the local GraphRAG index and merges results with web search.
    """
    _scout = scout_tool or ScoutTool()
    _graphrag = graphrag_tool

    async def scout_node(state: ResearchState) -> dict[str, Any]:
        query = state.get("current_query", "").strip()
        new_iteration = state.get("iteration_count", 0) + 1
        update: dict[str, Any] = {"iteration_count": new_iteration}

        new_docs, unseen_paths = _poll_new_resource_documents(state)
        if new_docs:
            logger.info(
                "Scout node (iteration %d): ingested %d newly added local resource document(s).",
                new_iteration,
                len(new_docs),
            )
            update["documents"] = new_docs
        if unseen_paths:
            update["watched_resources_seen"] = unseen_paths

        if not query:
            logger.warning(
                "Scout node (iteration %d): empty query — skipping acquisition.",
                new_iteration,
            )
            return update

        entity_hint = _build_entity_hint(state)
        constraint_hint = _build_constraint_hint(state)
        effective_query = f"{query}{entity_hint}{constraint_hint}" if (entity_hint or constraint_hint) else query

        # --- GraphRAG local corpus query (when available) ---
        graphrag_docs: list[dict[str, Any]] = []
        if _graphrag is not None:
            try:
                graphrag_docs = await _graphrag.query(query)
                if graphrag_docs:
                    logger.info(
                        "Scout node (iteration %d): retrieved %d GraphRAG document(s) for %r.",
                        new_iteration,
                        len(graphrag_docs),
                        query,
                    )
            except Exception as exc:
                logger.warning("Scout node: GraphRAG query failed — %s", exc)

        # --- Web search via ScoutTool ---
        docs = await _scout.acquire(effective_query)
        doc_dicts = [doc.model_dump(mode="json") for doc in docs]
        logger.info(
            "Scout node (iteration %d): acquired %d documents for query %r.",
            new_iteration,
            len(doc_dicts),
            effective_query,
        )

        # Merge GraphRAG + web results.
        all_docs = graphrag_docs + doc_dicts

        # Returning a list for 'documents' extends the existing list via
        # operator.add (the Annotated reducer declared in ResearchState).
        if all_docs:
            update.setdefault("documents", [])
            update["documents"] = list(update["documents"]) + all_docs
        return update

    return scout_node
