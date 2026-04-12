# Copyright (C) 2026 Microsoft
# Licensed under the MIT License

"""A module containing run_workflow method definition."""

import logging
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd

from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag.data_model.schemas import (
    ENTITIES_FINAL_COLUMNS,
    RELATIONSHIPS_FINAL_COLUMNS,
)
from graphrag.index.operations.snapshot_graphml import snapshot_graphml
from graphrag.index.typing.context import PipelineRunContext
from graphrag.index.typing.workflow import WorkflowFunctionOutput

logger = logging.getLogger(__name__)


async def run_workflow(
    config: GraphRagConfig,
    context: PipelineRunContext,
) -> WorkflowFunctionOutput:
    """Vectorized finalize_graph: degree map, dedup, and id assignment.

    Replaces three sequential row-by-row passes (each over millions of rows)
    with fully vectorized pandas operations, reducing runtime from hours to
    seconds on large corpora.
    """
    logger.info("Workflow started: finalize_graph")

    entities_df = await context.output_table_provider.read_dataframe("entities")
    relationships_df = await context.output_table_provider.read_dataframe("relationships")

    logger.info(
        "finalize_graph: %d entities, %d relationships (before dedup)",
        len(entities_df), len(relationships_df),
    )

    entities_out, relationships_out = _finalize_vectorized(entities_df, relationships_df)

    logger.info(
        "finalize_graph: writing %d entities, %d relationships (after dedup)",
        len(entities_out), len(relationships_out),
    )

    await context.output_table_provider.write_dataframe("entities", entities_out)
    await context.output_table_provider.write_dataframe("relationships", relationships_out)

    if config.snapshots.graphml:
        await snapshot_graphml(
            relationships_out, name="graph", storage=context.output_storage,
        )

    logger.info("Workflow completed: finalize_graph")
    return WorkflowFunctionOutput(
        result={
            "entities": entities_out.head(5).to_dict("records"),
            "relationships": relationships_out.head(5).to_dict("records"),
        }
    )


def _finalize_vectorized(
    entities_df: pd.DataFrame,
    relationships_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Degree map, dedup, and id assignment — fully vectorized.

    Notes
    -----
    Original implementation used three ``async for row in table`` loops over
    9.5M rows via ``pd.iterrows()``, creating a pandas Series per row —
    O(n) Python overhead that caused multi-hour hangs on large corpora.
    This replaces all three passes with vectorized NumPy/pandas operations.
    """
    # --- Degree map (undirected, dedup) ---
    src = relationships_df["source"].to_numpy(dtype=str)
    tgt = relationships_df["target"].to_numpy(dtype=str)
    lo = np.where(src <= tgt, src, tgt)
    hi = np.where(src <= tgt, tgt, src)
    edge_pairs = pd.DataFrame({"lo": lo, "hi": hi}).drop_duplicates()
    degree_map = pd.concat([edge_pairs["lo"], edge_pairs["hi"]]).value_counts().to_dict()

    # --- Relationships ---
    rels = relationships_df.drop_duplicates(subset=["source", "target"]).reset_index(drop=True).copy()
    rels["combined_degree"] = (
        rels["source"].map(degree_map).fillna(0).astype(int)
        + rels["target"].map(degree_map).fillna(0).astype(int)
    )
    rels["human_readable_id"] = rels.index
    rels["id"] = [str(uuid4()) for _ in range(len(rels))]
    rel_cols = [c for c in RELATIONSHIPS_FINAL_COLUMNS if c in rels.columns]
    rels_out = rels[rel_cols].copy()

    # --- Entities ---
    ents = entities_df.drop_duplicates(subset=["title"]).reset_index(drop=True).copy()
    ents["degree"] = ents["title"].map(degree_map).fillna(0).astype(int)
    ents["human_readable_id"] = ents.index
    ents["id"] = [str(uuid4()) for _ in range(len(ents))]
    ent_cols = [c for c in ENTITIES_FINAL_COLUMNS if c in ents.columns]
    ents_out = ents[ent_cols].copy()

    return ents_out, rels_out

