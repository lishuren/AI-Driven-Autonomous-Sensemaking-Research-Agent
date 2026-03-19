"""Tests for the Analyst extraction node.

All LLM calls are stubbed so tests run offline without any running inference
server.  Network isolation is achieved by patching
``sensemaking_agent.nodes.analyst_node.generate_text``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from sensemaking_agent.config import LLMConfig
from sensemaking_agent.nodes.analyst_node import (
    ExtractionResult,
    ExtractedEntity,
    ExtractedTriplet,
    _merge_entity,
    _parse_extraction,
    _triplet_id,
    make_analyst_node,
)
from sensemaking_agent.state import build_initial_state, merge_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc(
    doc_id: str = "doc_abc123",
    url: str = "https://example.com/article",
    title: str = "Test Article",
    content: str = "Lithium carbonate is used in EV batteries.",
    query: str = "EV supply chain",
) -> dict[str, Any]:
    return {
        "document_id": doc_id,
        "url": url,
        "title": title,
        "content": content,
        "source_type": "web",
        "query": query,
        "retrieved_at": "2026-03-19T00:00:00+00:00",
        "acquisition_method": "tavily_raw_content",
        "metadata": {},
    }


def _extraction_json(
    entities: list[dict] | None = None,
    triplets: list[dict] | None = None,
) -> str:
    return json.dumps({
        "entities": entities or [],
        "triplets": triplets or [],
    })


_DEFAULT_ENTITIES = [
    {
        "canonical_name": "Lithium carbonate",
        "type": "chemical",
        "aliases": ["Li2CO3"],
        "description": "A lithium salt used in battery production.",
    }
]

_DEFAULT_TRIPLETS = [
    {
        "subject": "Lithium carbonate",
        "predicate": "enables",
        "object": "EV battery production",
        "evidence": "Lithium carbonate is used in EV batteries.",
        "confidence": 0.92,
    }
]


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

class TestParseExtraction:
    def test_parses_valid_json(self) -> None:
        text = _extraction_json(_DEFAULT_ENTITIES, _DEFAULT_TRIPLETS)
        result = _parse_extraction(text)
        assert result is not None
        assert len(result.entities) == 1
        assert result.entities[0].canonical_name == "Lithium carbonate"
        assert len(result.triplets) == 1
        assert result.triplets[0].predicate == "enables"

    def test_parses_json_with_preamble(self) -> None:
        text = "Here is your extraction:\n" + _extraction_json(_DEFAULT_ENTITIES, [])
        result = _parse_extraction(text)
        assert result is not None
        assert len(result.entities) == 1

    def test_returns_none_for_garbage(self) -> None:
        result = _parse_extraction("Sorry, I cannot extract anything.")
        assert result is None

    def test_returns_empty_lists_for_empty_json(self) -> None:
        result = _parse_extraction('{"entities": [], "triplets": []}')
        assert result is not None
        assert result.entities == []
        assert result.triplets == []

    def test_ignores_extra_fields(self) -> None:
        text = json.dumps({
            "entities": _DEFAULT_ENTITIES,
            "triplets": [],
            "unexpected_key": "ignored",
        })
        result = _parse_extraction(text)
        assert result is not None


class TestTripletId:
    def test_deterministic(self) -> None:
        id1 = _triplet_id("A", "drives", "B", "doc1")
        id2 = _triplet_id("A", "drives", "B", "doc1")
        assert id1 == id2

    def test_different_inputs_give_different_ids(self) -> None:
        assert _triplet_id("A", "drives", "B", "doc1") != _triplet_id("A", "drives", "C", "doc1")

    def test_has_trip_prefix(self) -> None:
        assert _triplet_id("X", "causes", "Y", "doc2").startswith("trip_")


class TestMergeEntity:
    def test_adds_new_entity(self) -> None:
        registry: dict[str, Any] = {}
        entity = ExtractedEntity(canonical_name="CATL", type="organization")
        _merge_entity(registry, entity, "doc1")
        assert "CATL" in registry
        assert registry["CATL"]["type"] == "organization"
        assert "doc1" in registry["CATL"]["source_document_ids"]

    def test_merges_existing_entity_aliases(self) -> None:
        registry: dict[str, Any] = {
            "CATL": {
                "canonical_name": "CATL",
                "aliases": ["Contemporary Amperex"],
                "source_document_ids": ["doc1"],
                "description": None,
            }
        }
        entity = ExtractedEntity(
            canonical_name="CATL",
            aliases=["CATL Co.", "Contemporary Amperex"],  # "Contemporary Amperex" is a dup
        )
        _merge_entity(registry, entity, "doc2")
        aliases = registry["CATL"]["aliases"]
        assert "CATL Co." in aliases
        assert aliases.count("Contemporary Amperex") == 1  # no duplicate

    def test_back_fills_description(self) -> None:
        registry: dict[str, Any] = {
            "BYD": {"canonical_name": "BYD", "description": None, "aliases": [], "source_document_ids": []}
        }
        entity = ExtractedEntity(canonical_name="BYD", description="Chinese EV manufacturer.")
        _merge_entity(registry, entity, "doc_x")
        assert registry["BYD"]["description"] == "Chinese EV manufacturer."

    def test_preserves_existing_description(self) -> None:
        registry: dict[str, Any] = {
            "BYD": {
                "canonical_name": "BYD",
                "description": "Original description.",
                "aliases": [],
                "source_document_ids": [],
            }
        }
        entity = ExtractedEntity(canonical_name="BYD", description="New description attempt.")
        _merge_entity(registry, entity, "doc_y")
        assert registry["BYD"]["description"] == "Original description."

    def test_skips_empty_canonical_name(self) -> None:
        registry: dict[str, Any] = {}
        entity = ExtractedEntity(canonical_name="  ")
        _merge_entity(registry, entity, "doc1")
        assert registry == {}


# ---------------------------------------------------------------------------
# Analyst node integration tests (LLM stubbed)
# ---------------------------------------------------------------------------

_PATCH_TARGET = "sensemaking_agent.nodes.analyst_node.generate_text"


class TestAnalystNodeReturn:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_documents(self) -> None:
        node = make_analyst_node(LLMConfig())
        state = build_initial_state("test query")
        result = await node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_docs_already_processed(self) -> None:
        """A doc whose ID already appears in a triplet should not be re-processed."""
        doc = _doc(doc_id="doc_001")
        state = merge_state(
            build_initial_state("test"),
            documents=[doc],
            triplets=[{
                "triplet_id": "trip_x",
                "subject": "A",
                "predicate": "drives",
                "object": "B",
                "evidence": "A drives B.",
                "source_document_id": "doc_001",
                "source_url": None,
                "confidence": 0.9,
                "extraction_iteration": 1,
            }],
        )
        node = make_analyst_node(LLMConfig())
        with patch(_PATCH_TARGET, new=AsyncMock(return_value=None)):
            result = await node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_entities_and_triplets_populated_from_llm_response(self) -> None:
        doc = _doc()
        state = merge_state(build_initial_state("EV supply chain"), documents=[doc])
        llm_response = _extraction_json(_DEFAULT_ENTITIES, _DEFAULT_TRIPLETS)

        node = make_analyst_node(LLMConfig())
        with patch(_PATCH_TARGET, new=AsyncMock(return_value=llm_response)):
            result = await node(state)

        assert "entities" in result
        assert "Lithium carbonate" in result["entities"]
        assert "triplets" in result
        assert len(result["triplets"]) == 1
        assert result["triplets"][0]["predicate"] == "enables"
        assert result["triplets"][0]["source_document_id"] == doc["document_id"]

    @pytest.mark.asyncio
    async def test_triplet_id_is_deterministic(self) -> None:
        doc = _doc()
        state = merge_state(build_initial_state("test"), documents=[doc])
        llm_response = _extraction_json(_DEFAULT_ENTITIES, _DEFAULT_TRIPLETS)

        node = make_analyst_node(LLMConfig())
        with patch(_PATCH_TARGET, new=AsyncMock(return_value=llm_response)):
            result1 = await node(state)

        with patch(_PATCH_TARGET, new=AsyncMock(return_value=llm_response)):
            result2 = await node(state)

        assert result1["triplets"][0]["triplet_id"] == result2["triplets"][0]["triplet_id"]

    @pytest.mark.asyncio
    async def test_handles_llm_failure_gracefully(self) -> None:
        """When LLM returns None (failure), the node returns only entities (empty)."""
        doc = _doc()
        state = merge_state(build_initial_state("test"), documents=[doc])

        node = make_analyst_node(LLMConfig())
        with patch(_PATCH_TARGET, new=AsyncMock(return_value=None)):
            result = await node(state)

        # 'entities' should still be returned (merged registry, possibly empty)
        assert "entities" in result
        assert "triplets" not in result or result.get("triplets") == []

    @pytest.mark.asyncio
    async def test_handles_invalid_json_from_llm(self) -> None:
        doc = _doc()
        state = merge_state(build_initial_state("test"), documents=[doc])

        node = make_analyst_node(LLMConfig())
        with patch(_PATCH_TARGET, new=AsyncMock(return_value="not valid json at all")):
            result = await node(state)

        assert "triplets" not in result or result.get("triplets") == []

    @pytest.mark.asyncio
    async def test_skips_triplets_with_missing_fields(self) -> None:
        incomplete_triplets = [
            {"subject": "", "predicate": "drives", "object": "B", "evidence": "text", "confidence": 0.8},
        ]
        llm_response = _extraction_json([], incomplete_triplets)
        doc = _doc()
        state = merge_state(build_initial_state("test"), documents=[doc])

        node = make_analyst_node(LLMConfig())
        with patch(_PATCH_TARGET, new=AsyncMock(return_value=llm_response)):
            result = await node(state)

        assert not result.get("triplets")

    @pytest.mark.asyncio
    async def test_merges_entities_from_existing_registry(self) -> None:
        """Entities already in state should be preserved and merged, not overwritten."""
        existing_entity = {
            "canonical_name": "Tesla",
            "type": "organization",
            "aliases": [],
            "description": "EV manufacturer.",
            "evidence_refs": [],
            "source_document_ids": ["doc_old"],
            "confidence": None,
        }
        doc = _doc(doc_id="doc_new")
        state = merge_state(
            build_initial_state("test"),
            documents=[doc],
            entities={"Tesla": existing_entity},
        )

        new_entities = [
            {"canonical_name": "Lithium carbonate", "type": "chemical", "aliases": [], "description": "A salt."}
        ]
        llm_response = _extraction_json(new_entities, [])

        node = make_analyst_node(LLMConfig())
        with patch(_PATCH_TARGET, new=AsyncMock(return_value=llm_response)):
            result = await node(state)

        assert "Tesla" in result["entities"], "Existing entity should be preserved"
        assert "Lithium carbonate" in result["entities"], "New entity should be added"

    @pytest.mark.asyncio
    async def test_content_is_passed_to_llm(self) -> None:
        doc = _doc(content="The content of the document.")
        state = merge_state(build_initial_state("test"), documents=[doc])
        captured_prompts: list[str] = []

        async def capture_prompt(prompt: str, **kwargs: Any) -> str:
            captured_prompts.append(prompt)
            return _extraction_json([], [])

        node = make_analyst_node(LLMConfig())
        with patch(_PATCH_TARGET, new=capture_prompt):
            await node(state)

        assert captured_prompts, "LLM should have been called"
        assert "The content of the document." in captured_prompts[0]

    @pytest.mark.asyncio
    async def test_content_truncated_by_max_content_chars(self) -> None:
        long_content = "x" * 10_000
        doc = _doc(content=long_content)
        state = merge_state(build_initial_state("test"), documents=[doc])
        captured_prompts: list[str] = []

        async def capture(prompt: str, **kwargs: Any) -> str:
            captured_prompts.append(prompt)
            return _extraction_json([], [])

        config = LLMConfig(max_content_chars=500)
        node = make_analyst_node(config)
        with patch(_PATCH_TARGET, new=capture):
            await node(state)

        assert "x" * 501 not in captured_prompts[0], "Content should be truncated"
