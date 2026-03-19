"""Tests for the Critic contradiction-and-gap detection node.

All LLM calls are stubbed so tests run offline.  Network isolation is achieved
by patching ``sensemaking_agent.nodes.critic_node.generate_text``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from sensemaking_agent.config import LLMConfig
from sensemaking_agent.nodes.critic_node import (
    CriticResult,
    ExtractedContradiction,
    ExtractedGap,
    _contradiction_id,
    _gap_id,
    _parse_critic_result,
    _priority_value,
    _severity_value,
    make_critic_node,
)
from sensemaking_agent.state import build_initial_state, merge_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _triplet(
    subject: str = "lithium",
    predicate: str = "used_in",
    obj: str = "EV batteries",
    evidence: str = "Lithium is used in EV batteries.",
    doc_id: str = "doc_001",
    iteration: int = 0,
) -> dict[str, Any]:
    return {
        "triplet_id": f"trip_{subject}_{predicate}",
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "evidence": evidence,
        "source_document_id": doc_id,
        "source_url": "https://example.com",
        "confidence": 0.9,
        "extraction_iteration": iteration,
    }


def _critic_json(
    contradictions: list[dict] | None = None,
    gaps: list[dict] | None = None,
) -> str:
    return json.dumps({
        "contradictions": contradictions or [],
        "research_gaps": gaps or [],
    })


# ---------------------------------------------------------------------------
# Unit tests: pure helpers
# ---------------------------------------------------------------------------

class TestSeverityPriority:
    def test_severity_valid_values(self):
        assert _severity_value("high") == "high"
        assert _severity_value("low") == "low"

    def test_severity_invalid_defaults_to_low(self):
        assert _severity_value("critical") == "low"
        assert _severity_value("") == "low"

    def test_priority_valid_values(self):
        assert _priority_value("high") == "high"
        assert _priority_value("medium") == "medium"
        assert _priority_value("low") == "low"

    def test_priority_invalid_defaults_to_medium(self):
        assert _priority_value("urgent") == "medium"
        assert _priority_value("") == "medium"


class TestIdHelpers:
    def test_contradiction_id_stable(self):
        cid = _contradiction_id("lithium", "claim A", "claim B")
        assert cid.startswith("con_")
        assert cid == _contradiction_id("lithium", "claim A", "claim B")

    def test_contradiction_id_different_for_different_claims(self):
        assert _contradiction_id("X", "A", "B") != _contradiction_id("X", "A", "C")

    def test_gap_id_stable(self):
        gid = _gap_id("What drives lithium demand?")
        assert gid.startswith("gap_")
        assert gid == _gap_id("What drives lithium demand?")

    def test_gap_id_different_for_different_questions(self):
        assert _gap_id("Q1") != _gap_id("Q2")


class TestParseCriticResult:
    def test_parse_valid_json(self):
        raw = _critic_json(
            contradictions=[{
                "subject": "lithium",
                "topic": "demand driver",
                "claim_a": "EVs drive demand",
                "claim_b": "Grid storage drives demand",
                "evidence_a": "EV adoption rises",
                "evidence_b": "Grid projects expand",
                "severity": "high",
            }],
            gaps=[{
                "question": "What is the recycling rate for lithium?",
                "trigger": "lithium recycling",
                "priority": "medium",
            }],
        )
        result = _parse_critic_result(raw)
        assert result is not None
        assert len(result.contradictions) == 1
        assert result.contradictions[0].subject == "lithium"
        assert result.contradictions[0].severity == "high"
        assert len(result.research_gaps) == 1
        assert result.research_gaps[0].priority == "medium"

    def test_parse_json_with_preamble(self):
        raw = "Sure, here is the result:\n" + _critic_json()
        result = _parse_critic_result(raw)
        assert result is not None
        assert result.contradictions == []

    def test_parse_empty_lists(self):
        result = _parse_critic_result(_critic_json())
        assert result is not None
        assert result.contradictions == []
        assert result.research_gaps == []

    def test_parse_invalid_returns_none(self):
        assert _parse_critic_result("not json at all") is None

    def test_extra_fields_ignored(self):
        raw = json.dumps({
            "contradictions": [],
            "research_gaps": [],
            "unexpected_field": "ignored",
        })
        result = _parse_critic_result(raw)
        assert result is not None

    def test_missing_optional_fields_use_defaults(self):
        raw = json.dumps({
            "contradictions": [{
                "subject": "X",
                "topic": "T",
                "claim_a": "A",
                "claim_b": "B",
            }],
            "research_gaps": [{
                "question": "Q?",
                "trigger": "T",
            }],
        })
        result = _parse_critic_result(raw)
        assert result is not None
        assert result.contradictions[0].severity == "low"
        assert result.research_gaps[0].priority == "medium"


# ---------------------------------------------------------------------------
# Integration tests: make_critic_node factory
# ---------------------------------------------------------------------------

class TestMakeCriticNodeNoNewTriplets:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_triplets(self):
        node = make_critic_node(LLMConfig())
        state = build_initial_state("test query")
        result = await node(state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_triplets_prior_iterations(self):
        node = make_critic_node(LLMConfig())
        state = build_initial_state("test query")
        state = merge_state(
            state,
            triplets=[_triplet(iteration=0)],
            iteration_count=1,  # current is 1, triplet is from iteration 0
        )
        result = await node(state)
        assert result == {}


class TestMakeCriticNodeLLMContradiction:
    @pytest.mark.asyncio
    async def test_detects_contradiction(self):
        llm_response = _critic_json(
            contradictions=[{
                "subject": "lithium",
                "topic": "demand driver",
                "claim_a": "EVs are the primary demand driver",
                "claim_b": "Grid storage is the primary demand driver",
                "evidence_a": "EV sales rose 30%",
                "evidence_b": "Grid projects consume 40% of output",
                "severity": "high",
            }],
        )
        node = make_critic_node(LLMConfig())
        state = build_initial_state("lithium supply chain")
        state = merge_state(
            state,
            triplets=[_triplet(iteration=0)],
            iteration_count=0,
        )

        with patch(
            "sensemaking_agent.nodes.critic_node.generate_text",
            new=AsyncMock(return_value=llm_response),
        ):
            result = await node(state)

        assert "contradictions" in result
        assert len(result["contradictions"]) == 1
        con = result["contradictions"][0]
        assert con["contradiction_id"].startswith("con_")
        assert con["severity"] == "high"
        assert con["status"] == "open"
        assert con["topic"] == "demand driver"
        assert con["claim_a"] == "EVs are the primary demand driver"
        assert con["claim_b"] == "Grid storage is the primary demand driver"

    @pytest.mark.asyncio
    async def test_detects_research_gap(self):
        llm_response = _critic_json(
            gaps=[{
                "question": "What is the recycling rate for lithium?",
                "trigger": "lithium recycling",
                "priority": "high",
            }],
        )
        node = make_critic_node(LLMConfig())
        state = build_initial_state("lithium supply chain")
        state = merge_state(
            state,
            triplets=[_triplet(iteration=0)],
            iteration_count=0,
        )

        with patch(
            "sensemaking_agent.nodes.critic_node.generate_text",
            new=AsyncMock(return_value=llm_response),
        ):
            result = await node(state)

        assert "research_gaps" in result
        assert len(result["research_gaps"]) == 1
        gap = result["research_gaps"][0]
        assert gap["gap_id"].startswith("gap_")
        assert gap["priority"] == "high"
        assert gap["status"] == "open"
        assert gap["created_iteration"] == 0
        assert gap["resolved_iteration"] is None

    @pytest.mark.asyncio
    async def test_no_contradictions_no_gaps(self):
        node = make_critic_node(LLMConfig())
        state = build_initial_state("lithium supply chain")
        state = merge_state(
            state,
            triplets=[_triplet(iteration=0)],
            iteration_count=0,
        )

        with patch(
            "sensemaking_agent.nodes.critic_node.generate_text",
            new=AsyncMock(return_value=_critic_json()),
        ):
            result = await node(state)

        assert result == {}

    @pytest.mark.asyncio
    async def test_invalid_llm_response_returns_empty(self):
        node = make_critic_node(LLMConfig())
        state = build_initial_state("test")
        state = merge_state(
            state,
            triplets=[_triplet(iteration=0)],
            iteration_count=0,
        )

        with patch(
            "sensemaking_agent.nodes.critic_node.generate_text",
            new=AsyncMock(return_value="not valid json"),
        ):
            result = await node(state)

        assert result == {}

    @pytest.mark.asyncio
    async def test_none_llm_response_returns_empty(self):
        node = make_critic_node(LLMConfig())
        state = build_initial_state("test")
        state = merge_state(
            state,
            triplets=[_triplet(iteration=0)],
            iteration_count=0,
        )

        with patch(
            "sensemaking_agent.nodes.critic_node.generate_text",
            new=AsyncMock(return_value=None),
        ):
            result = await node(state)

        assert result == {}


class TestMakeCriticNodeDeduplication:
    @pytest.mark.asyncio
    async def test_skips_duplicate_contradiction(self):
        """Contradiction already in state must not be re-added."""
        cid = _contradiction_id("lithium", "EVs are primary", "Grid is primary")
        existing_con = {
            "contradiction_id": cid,
            "topic": "demand driver",
            "claim_a": "EVs are primary",
            "claim_b": "Grid is primary",
            "evidence_a": None,
            "evidence_b": None,
            "source_document_id_a": None,
            "source_document_id_b": None,
            "severity": "high",
            "status": "open",
            "resolution_notes": None,
        }
        llm_response = _critic_json(
            contradictions=[{
                "subject": "lithium",
                "topic": "demand driver",
                "claim_a": "EVs are primary",
                "claim_b": "Grid is primary",
                "severity": "high",
            }],
        )
        node = make_critic_node(LLMConfig())
        state = build_initial_state("lithium")
        state = merge_state(
            state,
            triplets=[_triplet(iteration=0)],
            contradictions=[existing_con],
            iteration_count=0,
        )

        with patch(
            "sensemaking_agent.nodes.critic_node.generate_text",
            new=AsyncMock(return_value=llm_response),
        ):
            result = await node(state)

        # No new contradictions should be added.
        assert result.get("contradictions", []) == []

    @pytest.mark.asyncio
    async def test_skips_duplicate_gap(self):
        """Gap already in state must not be re-added."""
        question = "What is the recycling rate for lithium?"
        gid = _gap_id(question)
        existing_gap = {
            "gap_id": gid,
            "question": question,
            "trigger": "recycling",
            "priority": "high",
            "status": "open",
            "created_iteration": 0,
            "resolved_iteration": None,
        }
        llm_response = _critic_json(
            gaps=[{
                "question": question,
                "trigger": "lithium recycling",
                "priority": "high",
            }],
        )
        node = make_critic_node(LLMConfig())
        state = build_initial_state("lithium")
        state = merge_state(
            state,
            triplets=[_triplet(iteration=0)],
            research_gaps=[existing_gap],
            iteration_count=0,
        )

        with patch(
            "sensemaking_agent.nodes.critic_node.generate_text",
            new=AsyncMock(return_value=llm_response),
        ):
            result = await node(state)

        assert result.get("research_gaps", []) == []


class TestMakeCriticNodeIterationFiltering:
    @pytest.mark.asyncio
    async def test_only_analyses_current_iteration_triplets(self):
        """LLM should be called only when triplets match current iteration."""
        node = make_critic_node(LLMConfig())
        state = build_initial_state("test")
        # Add triplet from iteration 1, but current iteration is 2.
        state = merge_state(
            state,
            triplets=[_triplet(iteration=1)],
            iteration_count=2,
        )

        with patch(
            "sensemaking_agent.nodes.critic_node.generate_text",
            new=AsyncMock(return_value=_critic_json()),
        ) as mock_llm:
            result = await node(state)

        mock_llm.assert_not_called()
        assert result == {}

    @pytest.mark.asyncio
    async def test_current_iteration_triplets_trigger_llm(self):
        """Triplets from the current iteration should cause an LLM call."""
        node = make_critic_node(LLMConfig())
        state = build_initial_state("test")
        state = merge_state(
            state,
            triplets=[_triplet(iteration=2)],
            iteration_count=2,
        )

        with patch(
            "sensemaking_agent.nodes.critic_node.generate_text",
            new=AsyncMock(return_value=_critic_json()),
        ) as mock_llm:
            await node(state)

        mock_llm.assert_called_once()


class TestMakeCriticNodePromptMissing:
    @pytest.mark.asyncio
    async def test_returns_empty_when_prompt_missing(self, tmp_path):
        """When the prompt file cannot be found, node returns empty dict."""
        with patch(
            "sensemaking_agent.nodes.critic_node.load_prompt",
            side_effect=FileNotFoundError,
        ):
            node = make_critic_node(LLMConfig())

        state = build_initial_state("test")
        state = merge_state(
            state,
            triplets=[_triplet(iteration=0)],
            iteration_count=0,
        )
        result = await node(state)
        assert result == {}


class TestMakeCriticNodeDefaultConfig:
    def test_factory_with_no_args_uses_default_llm_config(self):
        """make_critic_node() should not raise when no config is supplied."""
        node = make_critic_node()
        assert callable(node)

    def test_factory_with_explicit_config(self):
        node = make_critic_node(LLMConfig(model="test-model"))
        assert callable(node)
