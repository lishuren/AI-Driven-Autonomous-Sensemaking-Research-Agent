# State Schema

## Purpose

This document defines the canonical orchestration state for the Sensemaking
agent.

The state must support:

- additive accumulation of evidence
- graph construction across iterations
- contradiction-aware routing
- recursive gap resolution
- JSON-serializable persistence

## Design Goals

1. Keep the workflow state serializable.
2. Preserve provenance and evidence.
3. Make additive merges explicit.
4. Separate durable graph facts from transient routing metadata.
5. Keep the runtime graph derivable from stored state.

## Canonical ResearchState

The expected Python representation is a `TypedDict` or equivalent state object
with additive semantics for append-only collections.

Core fields:

```python
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class ResearchState(TypedDict, total=False):
    documents: Annotated[list[dict[str, Any]], operator.add]
    entities: dict[str, dict[str, Any]]
    triplets: Annotated[list[dict[str, Any]], operator.add]
    contradictions: Annotated[list[dict[str, Any]], operator.add]
    research_gaps: Annotated[list[dict[str, Any]], operator.add]
    current_query: str
    user_prompt: str
    constraints: str
    watched_resources_dir: str
    watched_resources_seen: Annotated[list[str], operator.add]
    iteration_count: int
    route_history: Annotated[list[dict[str, Any]], operator.add]
    metrics: dict[str, Any]
    final_synthesis: str
```

The exact implementation may use Pydantic models for nested structures, but the
workflow boundary should remain JSON-serializable.

## Documents

`documents` is the append-only record of normalized source material gathered by
Scout.

Minimum expected fields per document:

- `document_id`
- `url`
- `title`
- `content`
- `source_type`
- `query`
- `retrieved_at`
- `acquisition_method`
- `metadata`

Recommended example:

```python
{
    "document_id": "doc_001",
    "url": "https://example.com/article",
    "title": "Example title",
    "content": "normalized markdown or text",
    "source_type": "web",
    "query": "solid-state batteries EV supply chain",
    "retrieved_at": "2026-03-18T12:00:00Z",
    "acquisition_method": "tavily_extract",
    "metadata": {
        "domain": "example.com",
        "language": "en"
    }
}
```

## Entities

`entities` is the canonical entity registry.

It should be keyed by canonical entity name, with values such as:

- `type`
- `aliases`
- `description`
- `evidence_refs`
- `source_document_ids`
- `confidence`

Example:

```python
{
    "OpenAI": {
        "type": "organization",
        "aliases": ["OAI"],
        "description": "AI research and deployment company",
        "evidence_refs": ["triplet_014", "triplet_044"],
        "source_document_ids": ["doc_003"],
        "confidence": 0.93,
    }
}
```

## Triplets

`triplets` is the main relational memory layer.

Minimum expected fields:

- `triplet_id`
- `subject`
- `predicate`
- `object`
- `evidence`
- `source_document_id`
- `source_url`
- `confidence`
- `extraction_iteration`

Example:

```python
{
    "triplet_id": "triplet_014",
    "subject": "Lithium shortage",
    "predicate": "delays",
    "object": "EV production",
    "evidence": "Supply shortages in lithium have pushed back several EV programs.",
    "source_document_id": "doc_005",
    "source_url": "https://example.com/ev-report",
    "confidence": 0.87,
    "extraction_iteration": 2,
}
```

Triplets should be append-only at the workflow level. Deduplication, if used,
should preserve provenance rather than erasing independently sourced evidence.

## Contradictions

`contradictions` records conflicts between claims.

Minimum expected fields:

- `contradiction_id`
- `topic`
- `claim_a`
- `claim_b`
- `evidence_a`
- `evidence_b`
- `source_document_id_a`
- `source_document_id_b`
- `severity`
- `status`
- `resolution_notes`

Suggested status values:

- `open`
- `investigating`
- `resolved`
- `accepted_uncertainty`

## Research Gaps

`research_gaps` records missing context the router may send back to Scout.

Minimum expected fields:

- `gap_id`
- `question`
- `trigger`
- `priority`
- `status`
- `created_iteration`
- `resolved_iteration`

Example triggers:

- unexplained jargon
- missing prerequisite concept
- ambiguous mechanism
- missing authoritative verification source

## Routing Metadata

### `current_query`

The active search target for the next Scout pass.

### `user_prompt`

Background context derived from `requirements.md` sections such as
`## Research Focus` and `## Background`. This is injected into LLM-facing nodes.

### `constraints`

Optional guardrails derived from a `## Constraints` section in `requirements.md`.
This field is carried through the workflow so Critic analysis and Scout query
shaping can stay aligned with the user's intended scope.

### `watched_resources_dir`

Optional runtime-only path used when `--watch` is enabled. It tells Scout where
to poll for newly added local resource files between iterations.

### `watched_resources_seen`

Append-only list of local file paths already observed during a watch-mode run.
This prevents the same resource from being re-ingested every iteration.

### `iteration_count`

The main loop guard.

### `route_history`

Append-only record of routing decisions.

Suggested fields:

- `iteration`
- `route`
- `reason`
- `target`
- `timestamp`

### `metrics`

Optional counters useful for router decisions and observability.

Suggested metrics:

- `triplet_count`
- `entity_count`
- `open_contradiction_count`
- `high_severity_contradiction_count`
- `open_gap_count`
- `new_triplets_last_iteration`
- `graph_growth_ratio`

### `final_synthesis`

The final human-readable report content written by Writer.

## Merge Semantics

Expected merge behavior:

- append documents
- append triplets
- append contradictions
- append route history
- append research gaps unless an implementation-specific dedupe policy merges
  exact duplicates
- replace or merge scalar metadata deliberately, never accidentally

If LangGraph reducers are used, additive list semantics should be explicit.

## Runtime Graph Helper

The runtime system should provide a helper that converts state into a
`networkx.DiGraph`.

Expected graph behavior:

- nodes correspond to canonical entities
- directed edges correspond to triplets
- edge metadata carries predicate, evidence, source, and confidence
- node metadata may track contradiction involvement and entity type

## Difference From V1

This schema is not a replacement for V1 `TopicGraph`.

- V1 `TopicGraph` organizes research tasks and subtopics.
- V2 `ResearchState` organizes evidence, graph claims, conflicts, and gaps.

Task decomposition may still exist in V2, but it must not replace the knowledge
graph as the primary memory model.