"""GraphRAG query wrapper — async interface to local, global, DRIFT, and basic search.

Loads parquet output files from a completed GraphRAG index and dispatches
queries via the ``graphrag.api`` query functions.

Public API
----------
``async query(target_dir, question, *, method, community_level, response_type)``
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """A single query result from GraphRAG."""
    content: str
    method: str
    context_data: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parquet loading helpers
# ---------------------------------------------------------------------------

def _load_parquet(path: Path) -> pd.DataFrame:
    """Load a parquet file, returning an empty DataFrame if not found."""
    if path.exists():
        return pd.read_parquet(path)
    logger.debug("query: parquet file not found — %s", path)
    return pd.DataFrame()


def _load_output_tables(output_dir: Path) -> dict[str, pd.DataFrame]:
    """Load all standard GraphRAG output parquet tables."""
    tables = {}
    table_names = [
        "entities",
        "communities",
        "community_reports",
        "text_units",
        "relationships",
        "covariates",
    ]
    for name in table_names:
        path = output_dir / f"{name}.parquet"
        tables[name] = _load_parquet(path)
    return tables


def _find_output_dir(target_dir: Path) -> Path:
    """Locate the output directory containing parquet files."""
    # Default: <target>/output/
    output = target_dir / "output"
    if output.is_dir():
        return output
    # Fallback: look directly in target_dir.
    if (target_dir / "entities.parquet").exists():
        return target_dir
    return output  # Return default even if not found.


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def query(
    target_dir: str | Path,
    question: str,
    *,
    method: str = "local",
    community_level: int = 2,
    response_type: str = "Multiple Paragraphs",
    verbose: bool = False,
) -> QueryResult:
    """Query a GraphRAG index.

    Parameters
    ----------
    target_dir:
        GraphRAG project root (contains ``settings.yaml`` and ``output/``).
    question:
        The query string.
    method:
        Search method: ``"local"``, ``"global"``, ``"drift"``, or ``"basic"``.
    community_level:
        Leiden hierarchy level for community reports.
    response_type:
        Desired response format (e.g. "Multiple Paragraphs", "Single Sentence").
    verbose:
        Enable verbose logging.

    Returns
    -------
    QueryResult
    """
    target = Path(target_dir)

    try:
        from graphrag.config.load_config import load_config
        config = load_config(target)
    except Exception as exc:
        logger.error("query: cannot load GraphRAG config from %s — %s", target, exc)
        return QueryResult(
            content=f"Error: cannot load GraphRAG configuration — {exc}",
            method=method,
        )

    output_dir = _find_output_dir(target)
    tables = _load_output_tables(output_dir)

    if tables["entities"].empty:
        return QueryResult(
            content="Error: no indexed data found. Run 'graphragloader index' first.",
            method=method,
        )

    dispatch = {
        "local": _query_local,
        "global": _query_global,
        "drift": _query_drift,
        "basic": _query_basic,
    }

    handler = dispatch.get(method)
    if handler is None:
        return QueryResult(
            content=f"Error: unknown search method '{method}'. Use local, global, drift, or basic.",
            method=method,
        )

    return await handler(
        config=config,
        tables=tables,
        question=question,
        community_level=community_level,
        response_type=response_type,
        verbose=verbose,
    )


async def _query_local(
    *,
    config: Any,
    tables: dict[str, pd.DataFrame],
    question: str,
    community_level: int,
    response_type: str,
    verbose: bool,
) -> QueryResult:
    """Run a local search."""
    from graphrag.api import local_search

    covariates = tables["covariates"] if not tables["covariates"].empty else None

    response, context = await local_search(
        config=config,
        entities=tables["entities"],
        communities=tables["communities"],
        community_reports=tables["community_reports"],
        text_units=tables["text_units"],
        relationships=tables["relationships"],
        covariates=covariates,
        community_level=community_level,
        response_type=response_type,
        query=question,
        verbose=verbose,
    )

    return QueryResult(
        content=str(response),
        method="local",
        context_data=context,
        metadata={"community_level": community_level},
    )


async def _query_global(
    *,
    config: Any,
    tables: dict[str, pd.DataFrame],
    question: str,
    community_level: int,
    response_type: str,
    verbose: bool,
) -> QueryResult:
    """Run a global search."""
    from graphrag.api import global_search

    response, context = await global_search(
        config=config,
        entities=tables["entities"],
        communities=tables["communities"],
        community_reports=tables["community_reports"],
        community_level=community_level,
        dynamic_community_selection=False,
        response_type=response_type,
        query=question,
        verbose=verbose,
    )

    return QueryResult(
        content=str(response),
        method="global",
        context_data=context,
        metadata={"community_level": community_level},
    )


async def _query_drift(
    *,
    config: Any,
    tables: dict[str, pd.DataFrame],
    question: str,
    community_level: int,
    response_type: str,
    verbose: bool,
) -> QueryResult:
    """Run a DRIFT search."""
    from graphrag.api import drift_search

    response, context = await drift_search(
        config=config,
        entities=tables["entities"],
        communities=tables["communities"],
        community_reports=tables["community_reports"],
        text_units=tables["text_units"],
        relationships=tables["relationships"],
        community_level=community_level,
        response_type=response_type,
        query=question,
        verbose=verbose,
    )

    return QueryResult(
        content=str(response),
        method="drift",
        context_data=context,
        metadata={"community_level": community_level},
    )


async def _query_basic(
    *,
    config: Any,
    tables: dict[str, pd.DataFrame],
    question: str,
    community_level: int,
    response_type: str,
    verbose: bool,
) -> QueryResult:
    """Run a basic (vector) search."""
    from graphrag.api import basic_search

    response, context = await basic_search(
        config=config,
        text_units=tables["text_units"],
        response_type=response_type,
        query=question,
        verbose=verbose,
    )

    return QueryResult(
        content=str(response),
        method="basic",
        context_data=context,
    )
