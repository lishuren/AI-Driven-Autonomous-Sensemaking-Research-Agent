from __future__ import annotations

from sensemaking_agent.graph import (
    RouteName,
    RouterConfig,
    apply_route_decision,
    should_continue,
)
from sensemaking_agent.state import build_initial_state, merge_state


def _triplet(triplet_id: str) -> dict[str, object]:
    return {
        "triplet_id": triplet_id,
        "subject": "Lithium shortage",
        "predicate": "delays",
        "object": "EV production",
        "evidence": "Lithium shortages are delaying EV production.",
        "source_document_id": "doc_001",
        "source_url": "https://example.com/report",
        "confidence": 0.87,
        "extraction_iteration": 1,
    }


def test_should_continue_finalizes_when_iteration_limit_reached() -> None:
    state = merge_state(build_initial_state("battery supply chain"), iteration_count=5)

    decision = should_continue(state, RouterConfig(max_iterations=5))

    assert decision.route == RouteName.FINALIZE
    assert "iteration limit" in decision.reason


def test_should_continue_prefers_conflict_resolution() -> None:
    state = merge_state(
        build_initial_state("battery supply chain"),
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
    )

    decision = should_continue(state)

    assert decision.route == RouteName.RESOLVE_CONFLICT
    assert decision.contradiction_id == "contradiction_001"
    assert decision.target_query is not None
    assert "EV production outlook" in decision.target_query


def test_should_continue_uses_gap_resolution_when_no_conflict_remains() -> None:
    state = merge_state(
        build_initial_state("battery supply chain"),
        research_gaps=[
            {
                "gap_id": "gap_001",
                "question": "What is spodumene refining capacity?",
                "trigger": "unexplained jargon",
                "priority": "high",
                "status": "open",
                "created_iteration": 1,
            }
        ],
    )

    decision = should_continue(state)

    assert decision.route == RouteName.RESOLVE_GAP
    assert decision.gap_id == "gap_001"
    assert decision.target_query == "What is spodumene refining capacity?"


def test_should_continue_finalizes_when_graph_is_stable() -> None:
    base = merge_state(build_initial_state("battery supply chain"), triplets=[_triplet("triplet_001")])
    stable = merge_state(base)

    decision = should_continue(stable)

    assert decision.route == RouteName.FINALIZE
    assert "saturation" in decision.reason


def test_should_continue_continues_when_graph_is_growing() -> None:
    base = merge_state(build_initial_state("battery supply chain"), triplets=[_triplet("triplet_001")])
    growing = merge_state(base, triplets=[_triplet("triplet_002")])

    decision = should_continue(growing)

    assert decision.route == RouteName.CONTINUE_RESEARCH
    assert decision.target_query == "battery supply chain"


def test_apply_route_decision_updates_current_query_and_route_history() -> None:
    state = build_initial_state("battery supply chain")
    decision = should_continue(
        merge_state(
            state,
            research_gaps=[
                {
                    "gap_id": "gap_001",
                    "question": "What is spodumene refining capacity?",
                    "trigger": "unexplained jargon",
                    "priority": "high",
                    "status": "open",
                    "created_iteration": 1,
                }
            ],
        )
    )

    updated = apply_route_decision(state, decision)

    assert updated["current_query"] == "What is spodumene refining capacity?"
    assert len(updated["route_history"]) == 1
    assert updated["route_history"][0]["route"] == "resolve_gap"