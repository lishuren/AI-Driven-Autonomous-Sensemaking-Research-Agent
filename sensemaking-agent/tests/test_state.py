from __future__ import annotations

from sensemaking_agent.state import build_initial_state, merge_state, state_to_digraph, validate_state


def _sample_document() -> dict[str, object]:
    return {
        "document_id": "doc_001",
        "url": "https://example.com/report",
        "title": "Battery Supply Report",
        "content": "Lithium shortages are delaying EV production.",
        "source_type": "web",
        "query": "battery supply chain",
        "acquisition_method": "tavily_extract",
        "metadata": {"domain": "example.com"},
    }


def _sample_entity_registry() -> dict[str, dict[str, object]]:
    return {
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
            "evidence_refs": ["triplet_001", "triplet_002"],
            "source_document_ids": ["doc_001"],
            "confidence": 0.88,
        },
    }


def _sample_triplet(triplet_id: str, predicate: str) -> dict[str, object]:
    return {
        "triplet_id": triplet_id,
        "subject": "Lithium shortage",
        "predicate": predicate,
        "object": "EV production",
        "evidence": "Lithium shortages are delaying EV production.",
        "source_document_id": "doc_001",
        "source_url": "https://example.com/report",
        "confidence": 0.87,
        "extraction_iteration": 1,
    }


def test_build_initial_state_sets_expected_defaults() -> None:
    state = build_initial_state("battery supply chain")

    assert state["current_query"] == "battery supply chain"
    assert state["documents"] == []
    assert state["entities"] == {}
    assert state["constraints"] == ""
    assert state["watched_resources_dir"] == ""
    assert state["watched_resources_seen"] == []
    assert state["metrics"]["triplet_count"] == 0
    assert state["metrics"]["graph_growth_ratio"] == 0.0


def test_merge_state_appends_records_and_recomputes_metrics() -> None:
    base_state = build_initial_state("battery supply chain")

    merged = merge_state(
        base_state,
        documents=[_sample_document()],
        entities=_sample_entity_registry(),
        triplets=[_sample_triplet("triplet_001", "delays")],
        contradictions=[
            {
                "contradiction_id": "contradiction_001",
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
        route_history=[
            {
                "iteration": 1,
                "route": "continue_research",
                "reason": "new graph material added",
                "target": "battery supply chain",
            }
        ],
        iteration_count=1,
    )

    assert len(merged["documents"]) == 1
    assert len(merged["triplets"]) == 1
    assert merged["metrics"]["triplet_count"] == 1
    assert merged["metrics"]["entity_count"] == 2
    assert merged["metrics"]["high_severity_contradiction_count"] == 1
    assert merged["metrics"]["open_gap_count"] == 1
    assert merged["metrics"]["new_triplets_last_iteration"] == 1
    assert merged["metrics"]["graph_growth_ratio"] == 1.0


def test_validate_state_rehydrates_missing_optional_fields() -> None:
    validated = validate_state(
        {
            "current_query": "battery supply chain",
            "entities": {},
            "triplets": [],
        }
    )

    assert validated["documents"] == []
    assert validated["contradictions"] == []
    assert validated["research_gaps"] == []
    assert validated["route_history"] == []
    assert validated["constraints"] == ""
    assert validated["watched_resources_seen"] == []
    assert validated["metrics"]["triplet_count"] == 0


def test_merge_state_can_override_constraints() -> None:
    state = merge_state(
        build_initial_state("battery supply chain", constraints="old"),
        constraints="new",
    )

    assert state["constraints"] == "new"


def test_state_to_digraph_aggregates_triplets_on_same_edge() -> None:
    state = merge_state(
        build_initial_state("battery supply chain"),
        entities=_sample_entity_registry(),
        triplets=[
            _sample_triplet("triplet_001", "delays"),
            _sample_triplet("triplet_002", "constrains"),
        ],
        contradictions=[
            {
                "contradiction_id": "contradiction_001",
                "topic": "Lithium shortage impact",
                "claim_a": "Lithium shortage delays EV production.",
                "claim_b": "Lithium shortage no longer constrains EV production.",
                "severity": "high",
                "status": "open",
            }
        ],
    )

    graph = state_to_digraph(state)

    assert graph.has_node("Lithium shortage")
    assert graph.has_node("EV production")
    assert graph.nodes["Lithium shortage"]["disputed"] is True
    assert graph.has_edge("Lithium shortage", "EV production")
    assert graph["Lithium shortage"]["EV production"]["weight"] == 2
    assert sorted(graph["Lithium shortage"]["EV production"]["predicates"]) == [
        "constrains",
        "delays",
    ]