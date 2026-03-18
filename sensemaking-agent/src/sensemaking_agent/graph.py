from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict

from .state import ResearchState, merge_state, validate_state


class RouteName(StrEnum):
	CONTINUE_RESEARCH = "continue_research"
	RESOLVE_CONFLICT = "resolve_conflict"
	RESOLVE_GAP = "resolve_gap"
	FINALIZE = "finalize"


class RouterConfig(BaseModel):
	model_config = ConfigDict(extra="forbid")

	max_iterations: int = 5
	saturation_threshold: float = 0.10
	allow_conflict_resolution: bool = True
	allow_gap_resolution: bool = True


class RouteDecision(BaseModel):
	model_config = ConfigDict(extra="forbid")

	route: RouteName
	reason: str
	target_query: str | None = None
	contradiction_id: str | None = None
	gap_id: str | None = None


def graph_is_stable(
	state: Mapping[str, Any], *, saturation_threshold: float = 0.10
) -> bool:
	normalized = validate_state(state, recompute_metrics=False)
	growth_ratio = float(normalized["metrics"].get("graph_growth_ratio", 0.0))
	return growth_ratio <= saturation_threshold


def find_open_high_severity_contradiction(
	state: Mapping[str, Any],
) -> dict[str, Any] | None:
	normalized = validate_state(state, recompute_metrics=False)
	for contradiction in normalized["contradictions"]:
		if contradiction["status"] != "resolved" and contradiction["severity"] == "high":
			return contradiction
	return None


def find_open_priority_gap(
	state: Mapping[str, Any],
) -> dict[str, Any] | None:
	normalized = validate_state(state, recompute_metrics=False)
	priority_order = {"high": 0, "medium": 1, "low": 2}
	open_gaps = [gap for gap in normalized["research_gaps"] if gap["status"] != "resolved"]
	if not open_gaps:
		return None
	return sorted(open_gaps, key=lambda item: priority_order.get(item["priority"], 99))[0]


def build_gap_query(gap: Mapping[str, Any]) -> str:
	return str(gap["question"]).strip()


def build_conflict_query(contradiction: Mapping[str, Any]) -> str:
	topic = str(contradiction["topic"]).strip()
	claim_a = str(contradiction["claim_a"]).strip()
	claim_b = str(contradiction["claim_b"]).strip()
	return f"Verify conflicting claims about {topic}: {claim_a} vs {claim_b}"


def should_continue(
	state: Mapping[str, Any], config: RouterConfig | None = None
) -> RouteDecision:
	normalized = validate_state(state, recompute_metrics=False)
	config = config or RouterConfig()

	if normalized["iteration_count"] >= config.max_iterations:
		return RouteDecision(
			route=RouteName.FINALIZE,
			reason="iteration limit reached",
		)

	contradiction = (
		find_open_high_severity_contradiction(normalized)
		if config.allow_conflict_resolution
		else None
	)
	if contradiction is not None:
		return RouteDecision(
			route=RouteName.RESOLVE_CONFLICT,
			reason="open high-severity contradiction requires verification",
			target_query=build_conflict_query(contradiction),
			contradiction_id=str(contradiction["contradiction_id"]),
		)

	gap = find_open_priority_gap(normalized) if config.allow_gap_resolution else None
	if gap is not None:
		return RouteDecision(
			route=RouteName.RESOLVE_GAP,
			reason="open research gap requires targeted follow-up",
			target_query=build_gap_query(gap),
			gap_id=str(gap["gap_id"]),
		)

	if graph_is_stable(normalized, saturation_threshold=config.saturation_threshold):
		return RouteDecision(
			route=RouteName.FINALIZE,
			reason="graph growth is below the saturation threshold",
		)

	return RouteDecision(
		route=RouteName.CONTINUE_RESEARCH,
		reason="graph is still growing and no blocking conflict or gap remains",
		target_query=normalized["current_query"],
	)


def apply_route_decision(
	state: Mapping[str, Any], decision: RouteDecision
) -> ResearchState:
	normalized = validate_state(state, recompute_metrics=False)
	next_query = decision.target_query or normalized["current_query"]
	route_record = {
		"iteration": normalized["iteration_count"],
		"route": str(decision.route),
		"reason": decision.reason,
		"target": decision.target_query,
	}
	return merge_state(
		normalized,
		current_query=next_query,
		route_history=[route_record],
	)