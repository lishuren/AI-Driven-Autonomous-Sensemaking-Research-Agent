"""Sensemaking agent package.

Provides the full sensemaking workflow: Scout document acquisition, Analyst
entity and triplet extraction, Critic contradiction and gap detection, Router
state-graph orchestration, and Writer graph-grounded report synthesis.
"""

from .graph import (
    RouteDecision,
    RouteName,
    RouterConfig,
    apply_route_decision,
    build_conflict_query,
    build_gap_query,
    find_open_high_severity_contradiction,
    find_open_priority_gap,
    graph_is_stable,
    should_continue,
)
from .state import (
    ContradictionRecord,
    EntityRecord,
    ResearchGapRecord,
    ResearchState,
    RouteRecord,
    SourceDocument,
    StateMetrics,
    TripletRecord,
    build_initial_state,
    merge_state,
    state_to_digraph,
    validate_state,
)

__all__ = [
    "RouteDecision",
    "RouteName",
    "RouterConfig",
    "apply_route_decision",
    "build_conflict_query",
    "build_gap_query",
    "ContradictionRecord",
    "EntityRecord",
    "find_open_high_severity_contradiction",
    "find_open_priority_gap",
    "graph_is_stable",
    "ResearchGapRecord",
    "ResearchState",
    "RouteRecord",
    "SourceDocument",
    "StateMetrics",
    "TripletRecord",
    "build_initial_state",
    "merge_state",
    "should_continue",
    "state_to_digraph",
    "validate_state",
]