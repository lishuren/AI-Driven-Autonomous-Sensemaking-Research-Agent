"""Tests for the LangGraph workflow shell.

All external I/O (Tavily, Playwright, LLM) is stubbed so the tests run
offline without any API keys or installed browsers.

The tests verify:
- the workflow compiles without error
- a run with no search results terminates via the finalization path
  (graph is stable because no triplets grow) and returns final_synthesis
- iteration_count advances on each Scout pass
- Router correctly loops back to scout for a high-severity contradiction
  (but only up to max_iterations)
- the workflow terminates when Router decides to finalize immediately
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from sensemaking_agent.database import RunArtifactStore
from sensemaking_agent.graph import RouterConfig
from sensemaking_agent.state import build_initial_state
from sensemaking_agent.tools.scout_tool import ScoutTool
from sensemaking_agent.tools.search_tool import SearchTool
from sensemaking_agent.tools.scraper_tool import ScraperTool
from sensemaking_agent.workflow import build_workflow

_LLM_PATCH = "sensemaking_agent.nodes.analyst_node.generate_text"
_CRITIC_PATCH = "sensemaking_agent.nodes.critic_node.generate_text"
_WRITER_PATCH = "sensemaking_agent.nodes.writer_node.generate_text"
_EMPTY_EXTRACTION = json.dumps({"entities": [], "triplets": []})
_EMPTY_CRITIC_RESULT = json.dumps({"contradictions": [], "research_gaps": []})
_WRITER_RESPONSE = json.dumps(
    {
        "executive_summary": "Grid batteries stabilize renewable integration while the current graph shows limited unresolved uncertainty.",
        "knowledge_map": [
            {
                "insight": "Grid batteries stabilize renewable integration.",
                "supporting_triplet_ids": ["trip_demo"],
            }
        ],
        "key_pillars": [
            {
                "title": "Grid stability",
                "summary": "Battery storage acts as a stabilizing mechanism for renewable integration in the current graph.",
                "triplet_ids": ["trip_demo"],
            }
        ],
        "disputed_facts": [],
        "strategic_gaps": [],
        "evidence_trace": [
            {
                "claim": "Grid batteries stabilize renewable integration.",
                "triplet_ids": ["trip_demo"],
                "contradiction_ids": [],
                "source_document_ids": ["doc_demo"],
                "source_urls": ["https://example.com/doc1"],
            }
        ],
    }
)
_RICH_EXTRACTION = json.dumps(
    {
        "entities": [
            {
                "canonical_name": "Grid batteries",
                "type": "technology",
                "aliases": ["battery storage"],
                "description": "Grid-scale battery systems.",
            },
            {
                "canonical_name": "Renewable integration",
                "type": "process",
                "aliases": [],
                "description": "Adding variable renewable generation to the grid.",
            },
        ],
        "triplets": [
            {
                "subject": "Grid batteries",
                "predicate": "stabilize",
                "object": "Renewable integration",
                "evidence": "Grid batteries help stabilize renewable integration.",
                "confidence": 0.91,
            }
        ],
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stubbed_scout(results: list[dict[str, Any]] | None = None) -> ScoutTool:
    """Return a ScoutTool whose search method returns *results* (default: empty)."""
    search_tool = SearchTool()
    search_tool.search = AsyncMock(return_value=results or [])
    search_tool.extract = AsyncMock(return_value=[])
    scraper = ScraperTool()
    scraper.scrape = AsyncMock(return_value=None)  # type: ignore[method-assign]
    return ScoutTool(search_tool=search_tool, scraper_tool=scraper)


def _rich_result(url: str = "https://example.com/doc1") -> dict[str, Any]:
    return {
        "url": url,
        "title": "Test Article",
        "body": "Short snippet",
        "raw_content": "A" * 600,
    }


# ---------------------------------------------------------------------------
# Compile test
# ---------------------------------------------------------------------------

class TestWorkflowCompile:
    def test_build_workflow_returns_compiled_graph(self) -> None:
        workflow = build_workflow(scout_tool=_make_stubbed_scout())
        # A compiled LangGraph graph exposes ainvoke.
        assert callable(getattr(workflow, "ainvoke", None))


# ---------------------------------------------------------------------------
# End-to-end run tests
# ---------------------------------------------------------------------------

class TestWorkflowRun:
    @pytest.mark.asyncio
    async def test_workflow_terminates_with_no_results(self) -> None:
        """With no search results the graph stays empty and the router finalizes."""
        scout = _make_stubbed_scout(results=[])
        # max_iterations=1 forces early finalization, graph is stable from start
        config = RouterConfig(max_iterations=1)
        workflow = build_workflow(scout_tool=scout, router_config=config)

        initial = build_initial_state("test query")
        final = await workflow.ainvoke(initial)

        assert isinstance(final.get("final_synthesis"), str)
        assert len(final["final_synthesis"]) > 0

    @pytest.mark.asyncio
    async def test_iteration_count_increments(self) -> None:
        """iteration_count should be incremented by the Scout node each pass."""
        scout = _make_stubbed_scout(results=[])
        config = RouterConfig(max_iterations=1)
        workflow = build_workflow(scout_tool=scout, router_config=config)

        initial = build_initial_state("test query")
        final = await workflow.ainvoke(initial)

        # Scout ran at least once, so iteration_count >= 1.
        assert final.get("iteration_count", 0) >= 1

    @pytest.mark.asyncio
    async def test_documents_accumulated(self) -> None:
        """Documents returned by Scout should appear in the final state."""
        scout = _make_stubbed_scout(results=[_rich_result()])
        config = RouterConfig(max_iterations=1)
        workflow = build_workflow(scout_tool=scout, router_config=config)

        initial = build_initial_state("energy storage")
        with patch(_LLM_PATCH, new=AsyncMock(return_value=_EMPTY_EXTRACTION)):
            final = await workflow.ainvoke(initial)

        assert len(final.get("documents", [])) >= 1
        assert final["documents"][0]["url"] == "https://example.com/doc1"

    @pytest.mark.asyncio
    async def test_route_history_populated(self) -> None:
        """At least one route record should appear in route_history after a run."""
        scout = _make_stubbed_scout(results=[])
        config = RouterConfig(max_iterations=1)
        workflow = build_workflow(scout_tool=scout, router_config=config)

        initial = build_initial_state("climate change")
        final = await workflow.ainvoke(initial)

        assert len(final.get("route_history", [])) >= 1
        record = final["route_history"][0]
        assert "route" in record
        assert "reason" in record

    @pytest.mark.asyncio
    async def test_workflow_loops_when_contradiction_present(self) -> None:
        """Router should loop back to Scout when a high-severity contradiction is open.

        With max_iterations=2 the router gets two chances: first it routes to
        scout for the contradiction, then on the second iteration (count==2) it
        hits the iteration limit and finalizes.
        """
        scout = _make_stubbed_scout(results=[_rich_result()])
        config = RouterConfig(max_iterations=2)
        workflow = build_workflow(scout_tool=scout, router_config=config)

        # Inject an open high-severity contradiction into the initial state.
        from sensemaking_agent.state import merge_state

        initial = merge_state(
            build_initial_state("electric vehicles"),
            contradictions=[
                {
                    "contradiction_id": "c001",
                    "topic": "EV battery range",
                    "claim_a": "EV batteries last 500 miles.",
                    "claim_b": "EV batteries last 200 miles.",
                    "severity": "high",
                    "status": "open",
                }
            ],
        )

        with patch(_LLM_PATCH, new=AsyncMock(return_value=_EMPTY_EXTRACTION)):
            final = await workflow.ainvoke(initial)

        # The workflow should have completed (final_synthesis is set).
        assert isinstance(final.get("final_synthesis"), str)
        # iteration_count should have advanced past 1 due to the loop.
        assert final.get("iteration_count", 0) >= 2

    @pytest.mark.asyncio
    async def test_final_synthesis_contains_query(self) -> None:
        """The stub Writer should mention the original query in its output."""
        scout = _make_stubbed_scout(results=[])
        config = RouterConfig(max_iterations=1)
        workflow = build_workflow(scout_tool=scout, router_config=config)

        initial = build_initial_state("quantum computing breakthroughs")
        final = await workflow.ainvoke(initial)

        synthesis = final.get("final_synthesis", "")
        assert "quantum computing breakthroughs" in synthesis

    @pytest.mark.asyncio
    async def test_workflow_persists_checkpoint_and_final_artifacts(
        self, tmp_path: Path
    ) -> None:
        scout = _make_stubbed_scout(results=[_rich_result()])
        config = RouterConfig(max_iterations=1)
        store = RunArtifactStore(
            base_dir=tmp_path,
            query="grid storage",
            max_iterations=1,
        )
        workflow = build_workflow(
            scout_tool=scout,
            router_config=config,
            artifact_store=store,
        )

        initial = build_initial_state("grid storage")
        store.save_initial_state(initial)

        with patch(_LLM_PATCH, new=AsyncMock(return_value=_RICH_EXTRACTION)), patch(
            _CRITIC_PATCH,
            new=AsyncMock(return_value=_EMPTY_CRITIC_RESULT),
        ), patch(
            _WRITER_PATCH,
            new=AsyncMock(return_value=_WRITER_RESPONSE),
        ):
            final = await workflow.ainvoke(initial)

        checkpoint_path = store.run_dir / "checkpoint.iter-001.json"
        final_state_path = store.run_dir / "final_state.json"
        graph_path = store.run_dir / "graph.json"
        report_path = store.run_dir / "report.md"

        assert checkpoint_path.exists()
        assert final_state_path.exists()
        assert graph_path.exists()
        assert report_path.exists()
        assert final["metrics"]["triplet_count"] == 1

        saved_state = json.loads(final_state_path.read_text(encoding="utf-8"))
        saved_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))

        assert saved_state["metrics"]["triplet_count"] == 1
        assert saved_checkpoint["state"]["metrics"]["triplet_count"] == 1
        assert saved_checkpoint["route"] == "finalize"
        assert "## Executive Summary" in final["final_synthesis"]

    @pytest.mark.asyncio
    async def test_empty_query_does_not_crash(self) -> None:
        """An empty query should not raise — the Scout logs a warning and skips."""
        scout = _make_stubbed_scout(results=[])
        config = RouterConfig(max_iterations=1)
        workflow = build_workflow(scout_tool=scout, router_config=config)

        initial = build_initial_state("placeholder")
        # Override the query to empty after building to simulate edge case.
        initial["current_query"] = ""  # type: ignore[typeddict-unknown-key]

        final = await workflow.ainvoke(initial)

        assert final is not None
