"""Tests for the Writer synthesis helpers and node.

All LLM calls are stubbed so these tests run offline.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from sensemaking_agent.config import LLMConfig
from sensemaking_agent.nodes.writer_node import (
    WriterOutput,
    _parse_writer_output,
    make_writer_node,
)
from sensemaking_agent.state import build_initial_state, merge_state
from sensemaking_agent.synthesis import prepare_writer_context

_PATCH_TARGET = "sensemaking_agent.nodes.writer_node.generate_text"


def _sample_state():
    return merge_state(
        build_initial_state("grid resilience"),
        documents=[
            {
                "document_id": "doc_001",
                "url": "https://example.com/grid",
                "title": "Grid battery report",
                "content": "Battery storage stabilizes renewable-heavy grids.",
                "source_type": "web",
                "query": "grid resilience",
                "retrieved_at": "2026-04-01T00:00:00+00:00",
                "acquisition_method": "tavily_extract",
                "metadata": {},
            },
            {
                "document_id": "doc_002",
                "url": "https://example.com/solar",
                "title": "Solar integration note",
                "content": "Storage reduces renewable curtailment.",
                "source_type": "web",
                "query": "grid resilience",
                "retrieved_at": "2026-04-01T00:00:00+00:00",
                "acquisition_method": "tavily_extract",
                "metadata": {},
            },
        ],
        entities={
            "Grid batteries": {
                "type": "technology",
                "description": "Grid-scale battery systems.",
                "aliases": ["battery storage"],
                "evidence_refs": ["trip_001", "trip_002"],
                "source_document_ids": ["doc_001", "doc_002"],
                "confidence": 0.95,
            },
            "Renewable integration": {
                "type": "process",
                "description": "Adding variable renewable generation to the grid.",
                "aliases": [],
                "evidence_refs": ["trip_001", "trip_002"],
                "source_document_ids": ["doc_001", "doc_002"],
                "confidence": 0.9,
            },
            "Curtailment": {
                "type": "risk",
                "description": "Forced reduction in renewable output.",
                "aliases": [],
                "evidence_refs": ["trip_002"],
                "source_document_ids": ["doc_002"],
                "confidence": 0.82,
            },
        },
        triplets=[
            {
                "triplet_id": "trip_001",
                "subject": "Grid batteries",
                "predicate": "stabilize",
                "object": "Renewable integration",
                "evidence": "Battery storage stabilizes renewable-heavy grids.",
                "source_document_id": "doc_001",
                "source_url": "https://example.com/grid",
                "confidence": 0.96,
                "extraction_iteration": 1,
            },
            {
                "triplet_id": "trip_002",
                "subject": "Grid batteries",
                "predicate": "reduce",
                "object": "Curtailment",
                "evidence": "Storage reduces renewable curtailment.",
                "source_document_id": "doc_002",
                "source_url": "https://example.com/solar",
                "confidence": 0.92,
                "extraction_iteration": 1,
            },
        ],
        contradictions=[
            {
                "contradiction_id": "con_001",
                "topic": "Storage duration impact",
                "claim_a": "Short-duration batteries are enough for grid stability.",
                "claim_b": "Long-duration storage is required for grid stability.",
                "evidence_a": "One source favors short-duration systems.",
                "evidence_b": "Another source favors long-duration storage.",
                "source_document_id_a": "doc_001",
                "source_document_id_b": "doc_002",
                "severity": "high",
                "status": "open",
                "resolution_notes": None,
            }
        ],
        research_gaps=[
            {
                "gap_id": "gap_001",
                "question": "What storage duration is sufficient for renewable-heavy grids?",
                "trigger": "missing mechanism detail",
                "priority": "high",
                "status": "open",
                "created_iteration": 1,
                "resolved_iteration": None,
            }
        ],
        iteration_count=1,
    )


def _writer_json() -> str:
    return json.dumps(
        {
            "executive_summary": "Grid batteries stabilize renewable integration, but storage-duration evidence remains contested.",
            "knowledge_map": [
                {
                    "insight": "Grid batteries stabilize renewable integration.",
                    "supporting_triplet_ids": ["trip_001"],
                },
                {
                    "insight": "Grid batteries reduce curtailment.",
                    "supporting_triplet_ids": ["trip_002"],
                },
            ],
            "key_pillars": [
                {
                    "title": "Battery-enabled grid stability",
                    "summary": "Battery storage anchors the current graph by stabilizing renewable integration and reducing curtailment.",
                    "triplet_ids": ["trip_001", "trip_002"],
                }
            ],
            "disputed_facts": [
                {
                    "topic": "Storage duration impact",
                    "claim_a": "Short-duration batteries are enough for grid stability.",
                    "claim_b": "Long-duration storage is required for grid stability.",
                    "severity": "high",
                    "status": "open",
                    "explanation": "The evidence base splits between immediate balancing needs and longer-duration reliability requirements.",
                    "contradiction_id": "con_001",
                }
            ],
            "strategic_gaps": [
                {
                    "question": "What storage duration is sufficient for renewable-heavy grids?",
                    "priority": "high",
                    "status": "open",
                    "why_it_matters": "Duration assumptions change how the graph should be interpreted for reliability planning.",
                    "gap_id": "gap_001",
                }
            ],
            "evidence_trace": [
                {
                    "claim": "Grid batteries stabilize renewable integration.",
                    "triplet_ids": ["trip_001"],
                    "contradiction_ids": [],
                    "source_document_ids": ["doc_001"],
                    "source_urls": ["https://example.com/grid"],
                }
            ],
        }
    )


def test_prepare_writer_context_returns_bounded_payload() -> None:
    context = prepare_writer_context(
        _sample_state(),
        max_entities=2,
        max_triplets=2,
        max_contradictions=1,
        max_gaps=1,
        max_pillars=1,
        triplets_per_pillar=1,
    )

    assert len(context["top_entities"]) == 2
    assert len(context["representative_triplets"]) == 2
    assert len(context["contradictions"]) == 1
    assert len(context["research_gaps"]) == 1
    assert len(context["candidate_pillars"]) == 1
    assert context["top_entities"][0]["canonical_name"] == "Grid batteries"
    assert context["candidate_pillars"][0]["anchor_entity"] == "Grid batteries"


def test_parse_writer_output_accepts_valid_json() -> None:
    result = _parse_writer_output(_writer_json())
    assert isinstance(result, WriterOutput)
    assert result.executive_summary.startswith("Grid batteries")
    assert result.disputed_facts[0].contradiction_id == "con_001"


def test_parse_writer_output_accepts_preamble_json() -> None:
    result = _parse_writer_output("Here is the report\n" + _writer_json())
    assert isinstance(result, WriterOutput)
    assert result.key_pillars[0].title == "Battery-enabled grid stability"


@pytest.mark.asyncio
async def test_writer_node_renders_llm_output() -> None:
    node = make_writer_node(LLMConfig())

    with patch(_PATCH_TARGET, new=AsyncMock(return_value=_writer_json())):
        result = await node(_sample_state())

    synthesis = result["final_synthesis"]
    assert "## Executive Summary" in synthesis
    assert "## Disputed Facts" in synthesis
    assert "Storage duration impact" in synthesis
    assert "https://example.com/grid" in synthesis


@pytest.mark.asyncio
async def test_writer_node_falls_back_on_invalid_output() -> None:
    node = make_writer_node(LLMConfig())

    with patch(_PATCH_TARGET, new=AsyncMock(return_value="not json")):
        result = await node(_sample_state())

    synthesis = result["final_synthesis"]
    assert "## Executive Summary" in synthesis
    assert "## Strategic Gaps" in synthesis
    assert "Grid batteries stabilize" in synthesis
    assert "[Writer stub]" not in synthesis


@pytest.mark.asyncio
async def test_writer_node_uses_fallback_without_llm_for_empty_graph() -> None:
    node = make_writer_node(LLMConfig())
    state = build_initial_state("empty test")

    with patch(_PATCH_TARGET, new=AsyncMock(return_value=_writer_json())) as mocked:
        result = await node(state)

    mocked.assert_not_awaited()
    synthesis = result["final_synthesis"]
    assert "empty test" in synthesis
    assert "No high-salience graph relationships" in synthesis