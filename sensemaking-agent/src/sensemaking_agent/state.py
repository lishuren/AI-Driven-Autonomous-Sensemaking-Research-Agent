from __future__ import annotations

import operator
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, TypedDict, cast

import networkx as nx
from pydantic import BaseModel, ConfigDict, Field


class SourceDocumentState(TypedDict, total=False):
    document_id: str
    url: str
    title: str
    content: str
    source_type: str
    query: str
    retrieved_at: str
    acquisition_method: str
    metadata: dict[str, Any]


class EntityState(TypedDict, total=False):
    canonical_name: str
    type: str | None
    aliases: list[str]
    description: str | None
    evidence_refs: list[str]
    source_document_ids: list[str]
    confidence: float | None


class TripletState(TypedDict, total=False):
    triplet_id: str
    subject: str
    predicate: str
    object: str
    evidence: str
    source_document_id: str | None
    source_url: str | None
    confidence: float | None
    extraction_iteration: int


class ContradictionState(TypedDict, total=False):
    contradiction_id: str
    topic: str
    claim_a: str
    claim_b: str
    evidence_a: str | None
    evidence_b: str | None
    source_document_id_a: str | None
    source_document_id_b: str | None
    severity: Literal["low", "high"]
    status: Literal["open", "investigating", "resolved", "accepted_uncertainty"]
    resolution_notes: str | None


class ResearchGapState(TypedDict, total=False):
    gap_id: str
    question: str
    trigger: str
    priority: Literal["low", "medium", "high"]
    status: Literal["open", "investigating", "resolved"]
    created_iteration: int
    resolved_iteration: int | None


class RouteRecordState(TypedDict, total=False):
    iteration: int
    route: str
    reason: str
    target: str | None
    timestamp: str


class MetricsState(TypedDict, total=False):
    triplet_count: int
    entity_count: int
    open_contradiction_count: int
    high_severity_contradiction_count: int
    open_gap_count: int
    new_triplets_last_iteration: int
    graph_growth_ratio: float


class ResearchState(TypedDict, total=False):
    documents: Annotated[list[SourceDocumentState], operator.add]
    entities: dict[str, EntityState]
    triplets: Annotated[list[TripletState], operator.add]
    contradictions: Annotated[list[ContradictionState], operator.add]
    research_gaps: Annotated[list[ResearchGapState], operator.add]
    current_query: str
    user_prompt: str
    constraints: str
    watched_resources_dir: str
    watched_resources_seen: Annotated[list[str], operator.add]
    iteration_count: int
    route_history: Annotated[list[RouteRecordState], operator.add]
    metrics: MetricsState
    final_synthesis: str


class SourceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    url: str
    title: str
    content: str
    source_type: str = "web"
    query: str
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    acquisition_method: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str
    type: str | None = None
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None


class TripletRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    triplet_id: str
    subject: str
    predicate: str
    object: str
    evidence: str
    source_document_id: str | None = None
    source_url: str | None = None
    confidence: float | None = None
    extraction_iteration: int = 0


class ContradictionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contradiction_id: str
    topic: str
    claim_a: str
    claim_b: str
    evidence_a: str | None = None
    evidence_b: str | None = None
    source_document_id_a: str | None = None
    source_document_id_b: str | None = None
    severity: Literal["low", "high"] = "low"
    status: Literal["open", "investigating", "resolved", "accepted_uncertainty"] = "open"
    resolution_notes: str | None = None


class ResearchGapRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_id: str
    question: str
    trigger: str
    priority: Literal["low", "medium", "high"] = "medium"
    status: Literal["open", "investigating", "resolved"] = "open"
    created_iteration: int = 0
    resolved_iteration: int | None = None


class RouteRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iteration: int
    route: str
    reason: str
    target: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StateMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    triplet_count: int = 0
    entity_count: int = 0
    open_contradiction_count: int = 0
    high_severity_contradiction_count: int = 0
    open_gap_count: int = 0
    new_triplets_last_iteration: int = 0
    graph_growth_ratio: float = 0.0


def build_initial_state(
    current_query: str,
    *,
    documents: list[dict[str, object]] | None = None,
    user_prompt: str | None = None,
    constraints: str | None = None,
    watched_resources_dir: str | None = None,
) -> ResearchState:
    current_query = current_query.strip()
    if not current_query:
        raise ValueError("current_query must not be empty")

    state: ResearchState = {
        "documents": list(documents) if documents else [],
        "entities": {},
        "triplets": [],
        "contradictions": [],
        "research_gaps": [],
        "current_query": current_query,
        "user_prompt": user_prompt or "",
        "constraints": constraints or "",
        "watched_resources_dir": watched_resources_dir or "",
        "watched_resources_seen": [],
        "iteration_count": 0,
        "route_history": [],
        "metrics": StateMetrics().model_dump(mode="json"),
        "final_synthesis": "",
    }
    return state


def validate_state(
    state: Mapping[str, Any], *, recompute_metrics: bool = True
) -> ResearchState:
    validated_documents = [
        SourceDocument.model_validate(item).model_dump(mode="json")
        for item in state.get("documents", [])
    ]
    validated_entities = _validate_entities(state.get("entities", {}))
    validated_triplets = [
        TripletRecord.model_validate(item).model_dump(mode="json")
        for item in state.get("triplets", [])
    ]
    validated_contradictions = [
        ContradictionRecord.model_validate(item).model_dump(mode="json")
        for item in state.get("contradictions", [])
    ]
    validated_gaps = [
        ResearchGapRecord.model_validate(item).model_dump(mode="json")
        for item in state.get("research_gaps", [])
    ]
    validated_routes = [
        RouteRecord.model_validate(item).model_dump(mode="json")
        for item in state.get("route_history", [])
    ]

    normalized: ResearchState = {
        "documents": validated_documents,
        "entities": validated_entities,
        "triplets": validated_triplets,
        "contradictions": validated_contradictions,
        "research_gaps": validated_gaps,
        "current_query": str(state.get("current_query", "")).strip(),
        "user_prompt": str(state.get("user_prompt", "")),
        "constraints": str(state.get("constraints", "")),
        "watched_resources_dir": str(state.get("watched_resources_dir", "")),
        "watched_resources_seen": [str(p) for p in state.get("watched_resources_seen", [])],
        "iteration_count": int(state.get("iteration_count", 0)),
        "route_history": validated_routes,
        "metrics": StateMetrics.model_validate(state.get("metrics", {})).model_dump(mode="json"),
        "final_synthesis": str(state.get("final_synthesis", "")),
    }

    if recompute_metrics:
        normalized["metrics"] = compute_metrics(normalized).model_dump(mode="json")

    return normalized


def merge_state(
    base_state: Mapping[str, Any],
    *,
    documents: Sequence[Mapping[str, Any] | SourceDocument] = (),
    entities: Mapping[str, Mapping[str, Any] | EntityRecord] | None = None,
    triplets: Sequence[Mapping[str, Any] | TripletRecord] = (),
    contradictions: Sequence[Mapping[str, Any] | ContradictionRecord] = (),
    research_gaps: Sequence[Mapping[str, Any] | ResearchGapRecord] = (),
    route_history: Sequence[Mapping[str, Any] | RouteRecord] = (),
    current_query: str | None = None,
    iteration_count: int | None = None,
    final_synthesis: str | None = None,
    constraints: str | None = None,
) -> ResearchState:
    normalized_base = validate_state(base_state)
    previous_metrics = StateMetrics.model_validate(normalized_base.get("metrics", {}))

    merged: ResearchState = {
        "documents": list(normalized_base["documents"]),
        "entities": deepcopy(normalized_base["entities"]),
        "triplets": list(normalized_base["triplets"]),
        "contradictions": list(normalized_base["contradictions"]),
        "research_gaps": list(normalized_base["research_gaps"]),
        "current_query": normalized_base["current_query"],
        "user_prompt": normalized_base.get("user_prompt", ""),
        "constraints": normalized_base.get("constraints", ""),
        "watched_resources_dir": normalized_base.get("watched_resources_dir", ""),
        "watched_resources_seen": list(normalized_base.get("watched_resources_seen", [])),
        "iteration_count": normalized_base["iteration_count"],
        "route_history": list(normalized_base["route_history"]),
        "metrics": normalized_base["metrics"],
        "final_synthesis": normalized_base["final_synthesis"],
    }

    merged["documents"].extend(_dump_sequence(documents, SourceDocument))
    merged["triplets"].extend(_dump_sequence(triplets, TripletRecord))
    merged["contradictions"].extend(
        _dump_sequence(contradictions, ContradictionRecord)
    )
    merged["research_gaps"].extend(_dump_sequence(research_gaps, ResearchGapRecord))
    merged["route_history"].extend(_dump_sequence(route_history, RouteRecord))

    if entities:
        merged["entities"] = _merge_entities(merged["entities"], entities)

    if current_query is not None:
        merged["current_query"] = current_query.strip()
    if iteration_count is not None:
        merged["iteration_count"] = iteration_count
    if final_synthesis is not None:
        merged["final_synthesis"] = final_synthesis
    if constraints is not None:
        merged["constraints"] = constraints

    merged["metrics"] = compute_metrics(
        merged, previous_metrics=previous_metrics
    ).model_dump(mode="json")

    return validate_state(merged, recompute_metrics=False)


def compute_metrics(
    state: Mapping[str, Any], previous_metrics: StateMetrics | Mapping[str, Any] | None = None
) -> StateMetrics:
    normalized = validate_state(state, recompute_metrics=False)
    previous = (
        StateMetrics.model_validate(previous_metrics)
        if previous_metrics is not None
        else StateMetrics()
    )

    triplet_count = len(normalized["triplets"])
    entity_count = len(normalized["entities"])
    open_contradiction_count = sum(
        1 for item in normalized["contradictions"] if item["status"] != "resolved"
    )
    high_severity_contradiction_count = sum(
        1
        for item in normalized["contradictions"]
        if item["status"] != "resolved" and item["severity"] == "high"
    )
    open_gap_count = sum(
        1 for item in normalized["research_gaps"] if item["status"] != "resolved"
    )
    new_triplets_last_iteration = max(triplet_count - previous.triplet_count, 0)

    if previous.triplet_count > 0:
        graph_growth_ratio = new_triplets_last_iteration / previous.triplet_count
    elif triplet_count > 0:
        graph_growth_ratio = 1.0
    else:
        graph_growth_ratio = 0.0

    return StateMetrics(
        triplet_count=triplet_count,
        entity_count=entity_count,
        open_contradiction_count=open_contradiction_count,
        high_severity_contradiction_count=high_severity_contradiction_count,
        open_gap_count=open_gap_count,
        new_triplets_last_iteration=new_triplets_last_iteration,
        graph_growth_ratio=graph_growth_ratio,
    )


def state_to_digraph(state: Mapping[str, Any]) -> nx.DiGraph:
    normalized = validate_state(state)
    graph = nx.DiGraph()
    disputed_entities = _collect_disputed_entities(normalized)

    for canonical_name, entity in normalized["entities"].items():
        graph.add_node(
            canonical_name,
            **entity,
            disputed=canonical_name in disputed_entities,
        )

    for triplet in normalized["triplets"]:
        subject = triplet["subject"]
        obj = triplet["object"]

        if not graph.has_node(subject):
            graph.add_node(subject, canonical_name=subject, disputed=subject in disputed_entities)
        if not graph.has_node(obj):
            graph.add_node(obj, canonical_name=obj, disputed=obj in disputed_entities)

        if graph.has_edge(subject, obj):
            edge = graph[subject][obj]
            triplet_list = list(edge.get("triplets", []))
            triplet_list.append(triplet)
            edge["triplets"] = triplet_list
            edge["predicates"] = sorted({item["predicate"] for item in triplet_list})
            edge["weight"] = len(triplet_list)
        else:
            graph.add_edge(
                subject,
                obj,
                triplets=[triplet],
                predicates=[triplet["predicate"]],
                weight=1,
            )

    return graph


def _validate_entities(
    entities: Mapping[str, Any] | None,
) -> dict[str, EntityState]:
    if not entities:
        return {}

    validated: dict[str, EntityState] = {}
    for canonical_name, value in entities.items():
        payload = dict(value)
        payload.setdefault("canonical_name", canonical_name)
        record = EntityRecord.model_validate(payload).model_dump(mode="json")
        validated[canonical_name] = cast(EntityState, record)
    return validated


def _merge_entities(
    base_entities: Mapping[str, EntityState],
    updates: Mapping[str, Mapping[str, Any] | EntityRecord],
) -> dict[str, EntityState]:
    merged = deepcopy(dict(base_entities))
    for canonical_name, value in updates.items():
        payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
        payload.setdefault("canonical_name", canonical_name)
        merged[canonical_name] = cast(
            EntityState,
            EntityRecord.model_validate(payload).model_dump(mode="json"),
        )
    return merged


def _dump_sequence(
    items: Sequence[Mapping[str, Any] | BaseModel], model_type: type[BaseModel]
) -> list[dict[str, Any]]:
    dumped: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, BaseModel):
            record = item.model_dump(mode="json")
        else:
            record = model_type.model_validate(item).model_dump(mode="json")
        dumped.append(record)
    return dumped


def _collect_disputed_entities(state: Mapping[str, Any]) -> set[str]:
    normalized = validate_state(state, recompute_metrics=False)
    entity_names = list(normalized["entities"].keys())
    disputed: set[str] = set()

    for contradiction in normalized["contradictions"]:
        searchable_fields = [
            contradiction["topic"],
            contradiction["claim_a"],
            contradiction["claim_b"],
        ]
        for entity_name in entity_names:
            if any(entity_name.lower() in field.lower() for field in searchable_fields):
                disputed.add(entity_name)

    return disputed