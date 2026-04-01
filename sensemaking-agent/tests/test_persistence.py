from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import sensemaking_agent.main as main_module
from sensemaking_agent.database import RunArtifactStore
from sensemaking_agent.state import build_initial_state, merge_state


class _WorkflowDouble:
    def __init__(self, result_builder):
        self._result_builder = result_builder
        self.received_state = None

    async def ainvoke(self, state):
        self.received_state = state
        return self._result_builder(state)


def test_run_artifact_store_writes_checkpoint_and_final_outputs(tmp_path) -> None:
    store = RunArtifactStore(
        base_dir=tmp_path,
        query="battery supply chain",
        max_iterations=3,
    )

    initial = build_initial_state("battery supply chain")
    store.save_initial_state(initial)

    checkpoint_state = merge_state(
        initial,
        entities={
            "Lithium shortage": {
                "type": "concept",
                "description": "Persistent shortfall in lithium supply.",
                "aliases": [],
                "evidence_refs": ["triplet_001"],
                "source_document_ids": ["doc_001"],
                "confidence": 0.9,
            },
            "EV production": {
                "type": "process",
                "description": "Electric vehicle manufacturing output.",
                "aliases": [],
                "evidence_refs": ["triplet_001"],
                "source_document_ids": ["doc_001"],
                "confidence": 0.88,
            },
        },
        triplets=[
            {
                "triplet_id": "triplet_001",
                "subject": "Lithium shortage",
                "predicate": "delays",
                "object": "EV production",
                "evidence": "Lithium shortages are delaying EV production.",
                "source_document_id": "doc_001",
                "source_url": "https://example.com/report",
                "confidence": 0.87,
                "extraction_iteration": 1,
            }
        ],
        route_history=[
            {
                "iteration": 1,
                "route": "continue_research",
                "reason": "graph is still growing",
                "target": "battery supply chain",
            }
        ],
        iteration_count=1,
    )
    store.save_checkpoint(
        checkpoint_state,
        route="continue_research",
        reason="graph is still growing",
    )

    final_state = merge_state(
        checkpoint_state,
        final_synthesis="## Executive Summary\nLithium shortages delay EV production.",
    )
    store.save_final(final_state)

    manifest = json.loads((store.run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    checkpoint = json.loads(
        (store.run_dir / "checkpoint.iter-001.json").read_text(encoding="utf-8")
    )
    graph = json.loads((store.run_dir / "graph.json").read_text(encoding="utf-8"))
    report = (store.run_dir / "report.md").read_text(encoding="utf-8")
    graphml = (store.run_dir / "graph.graphml").read_text(encoding="utf-8")
    dot = (store.run_dir / "graph.dot").read_text(encoding="utf-8")
    viewer = (store.run_dir / "graph_viewer.html").read_text(encoding="utf-8")

    assert (store.run_dir / "initial_state.json").exists()
    assert manifest["query"] == "battery supply chain"
    assert manifest["last_checkpoint_iteration"] == 1
    assert manifest["final_iteration_count"] == 1
    assert manifest["graphml_file"] == "graph.graphml"
    assert manifest["dot_file"] == "graph.dot"
    assert manifest["html_viewer_file"] == "graph_viewer.html"
    assert checkpoint["state"]["triplets"][0]["predicate"] == "delays"
    assert graph["node_count"] == 2
    assert graph["edge_count"] == 1
    assert "Lithium shortages delay EV production." in report
    assert "graphml" in graphml
    assert "digraph sensemaking" in dot
    assert "Sensemaking graph viewer" in viewer


def test_find_latest_resumable_run_returns_latest_incomplete_match(tmp_path) -> None:
    query = "battery supply chain"

    completed = RunArtifactStore(base_dir=tmp_path, query=query, max_iterations=3)
    initial = build_initial_state(query)
    completed.save_initial_state(initial)
    completed.save_final(merge_state(initial, final_synthesis="done"))

    resumable = RunArtifactStore(base_dir=tmp_path, query=query, max_iterations=3)
    resumable.save_initial_state(initial)
    resumable_state = merge_state(initial, iteration_count=2)
    resumable.save_checkpoint(
        resumable_state,
        route="continue_research",
        reason="still gathering evidence",
    )

    found = RunArtifactStore.find_latest_resumable_run(tmp_path, query)

    assert found is not None
    assert found.run_dir == resumable.run_dir
    assert found.is_completed is False
    assert found.load_resume_state()["iteration_count"] == 2


@pytest.mark.asyncio
async def test_run_auto_resumes_latest_incomplete_run(tmp_path) -> None:
    query = "battery supply chain"
    store = RunArtifactStore(base_dir=tmp_path, query=query, max_iterations=3)

    initial = build_initial_state(query)
    store.save_initial_state(initial)
    checkpoint_state = merge_state(
        initial,
        iteration_count=2,
        route_history=[
            {
                "iteration": 2,
                "route": "continue_research",
                "reason": "resume me",
                "target": query,
            }
        ],
    )
    store.save_checkpoint(
        checkpoint_state,
        route="continue_research",
        reason="resume me",
    )

    workflow = _WorkflowDouble(
        lambda state: merge_state(state, final_synthesis="resumed run output")
    )

    with patch("sensemaking_agent.main.build_workflow", return_value=workflow):
        result = await main_module.run(query, 5, output_dir=tmp_path)

    assert result == "resumed run output"
    assert workflow.received_state is not None
    assert workflow.received_state["iteration_count"] == 2
    assert len([path for path in tmp_path.iterdir() if path.is_dir()]) == 1

    manifest = json.loads((store.run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["resume_count"] == 1
    assert (store.run_dir / "final_state.json").exists()


@pytest.mark.asyncio
async def test_run_starts_new_run_when_previous_run_is_completed(tmp_path) -> None:
    query = "battery supply chain"
    completed = RunArtifactStore(base_dir=tmp_path, query=query, max_iterations=3)
    initial = build_initial_state(query)
    completed.save_initial_state(initial)
    completed.save_final(merge_state(initial, final_synthesis="done"))

    workflow = _WorkflowDouble(
        lambda state: merge_state(state, final_synthesis="fresh run output")
    )

    with patch("sensemaking_agent.main.build_workflow", return_value=workflow):
        result = await main_module.run(query, 5, output_dir=tmp_path)

    assert result == "fresh run output"
    assert workflow.received_state is not None
    assert workflow.received_state["iteration_count"] == 0
    assert len([path for path in tmp_path.iterdir() if path.is_dir()]) == 2