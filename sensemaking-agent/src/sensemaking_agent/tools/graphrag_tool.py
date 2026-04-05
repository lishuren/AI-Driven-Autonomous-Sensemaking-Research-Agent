"""GraphRAG query tool for the sensemaking agent.

Thin async wrapper around ``graphragloader.query()`` that converts
GraphRAG results into ``SourceDocument``-compatible dicts.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_HAS_GRAPHRAGLOADER = False
try:
    from graphragloader.query import QueryResult, query as graphrag_query
    _HAS_GRAPHRAGLOADER = True
except ImportError:
    pass


@dataclass
class GraphRAGTool:
    """Async query interface to a pre-built GraphRAG index."""

    graphrag_dir: str
    method: str = "local"
    community_level: int = 2
    response_type: str = "Multiple Paragraphs"

    async def query(
        self,
        question: str,
        *,
        method: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Query the GraphRAG index and return SourceDocument-style dicts.

        Parameters
        ----------
        question:
            The query string.
        method:
            Override the default search method for this call.

        Returns
        -------
        list[dict]
            A list of document dicts compatible with ``SourceDocumentState``.
        """
        if not _HAS_GRAPHRAGLOADER:
            logger.warning(
                "graphrag_tool: graphragloader package not installed — "
                "cannot query GraphRAG index."
            )
            return []

        target = Path(self.graphrag_dir)
        if not target.is_dir():
            logger.warning("graphrag_tool: directory does not exist — %s", target)
            return []

        search_method = method or self.method

        try:
            result = await graphrag_query(
                target_dir=target,
                question=question,
                method=search_method,
                community_level=self.community_level,
                response_type=self.response_type,
            )
        except Exception as exc:
            logger.error("graphrag_tool: query failed — %s", exc)
            return []

        if not result or not result.content or result.content.startswith("Error:"):
            logger.debug("graphrag_tool: empty or error result for %r", question)
            return []

        return [_to_source_document(result, question)]


def _to_source_document(result: Any, question: str) -> dict[str, Any]:
    """Convert a ``QueryResult`` to a ``SourceDocumentState``-compatible dict."""
    import hashlib
    from datetime import datetime, timezone

    doc_id = hashlib.sha1(
        f"graphrag:{result.method}:{question}".encode()
    ).hexdigest()[:16]

    return {
        "document_id": f"graphrag-{doc_id}",
        "url": "",
        "title": f"GraphRAG {result.method} search: {question[:80]}",
        "content": result.content,
        "source_type": "graphrag",
        "query": question,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "acquisition_method": f"graphrag_{result.method}",
        "metadata": {
            "graphrag_method": result.method,
            **(result.metadata or {}),
        },
    }
