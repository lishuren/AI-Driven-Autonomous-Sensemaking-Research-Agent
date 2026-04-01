from __future__ import annotations

from sensemaking_agent.state import build_initial_state, merge_state
from sensemaking_agent.visualisation import (
    export_dot,
    export_graphml,
    export_html_viewer,
)


def _sample_state():
    return merge_state(
        build_initial_state("battery supply chain"),
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
        contradictions=[
            {
                "contradiction_id": "con_001",
                "topic": "EV production outlook",
                "claim_a": "Lithium shortage delays EV production.",
                "claim_b": "EV production is not constrained by lithium shortage.",
                "severity": "high",
                "status": "open",
            }
        ],
        research_gaps=[
            {
                "gap_id": "gap_001",
                "question": "What is spodumene refining capacity?",
                "trigger": "unexplained jargon",
                "priority": "medium",
                "status": "open",
                "created_iteration": 1,
            }
        ],
    )


def test_export_graphml_writes_expected_content(tmp_path) -> None:
    path = export_graphml(_sample_state(), tmp_path / "graph.graphml")
    text = path.read_text(encoding="utf-8")

    assert path.exists()
    assert "graphml" in text
    assert "Lithium shortage" in text
    assert "EV production" in text


def test_export_dot_writes_expected_content(tmp_path) -> None:
    path = export_dot(_sample_state(), tmp_path / "graph.dot")
    text = path.read_text(encoding="utf-8")

    assert path.exists()
    assert "digraph sensemaking" in text
    assert "Lithium shortage" in text
    assert "EV production" in text
    assert "delays" in text


def test_export_html_viewer_writes_expected_content(tmp_path) -> None:
    path = export_html_viewer(
        _sample_state(),
        tmp_path / "graph_viewer.html",
        title="Battery Supply Graph",
    )
    text = path.read_text(encoding="utf-8")

    assert path.exists()
    assert "Battery Supply Graph" in text
    assert "Sensemaking graph viewer" in text
    assert "Open Contradictions" in text
    assert "Research Gaps" in text