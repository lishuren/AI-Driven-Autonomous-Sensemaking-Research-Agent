from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

import networkx as nx

from .state import state_to_digraph, validate_state


def prepare_writer_context(
    state: Mapping[str, Any],
    *,
    max_entities: int = 8,
    max_triplets: int = 12,
    max_contradictions: int = 5,
    max_gaps: int = 5,
    max_pillars: int = 4,
    triplets_per_pillar: int = 4,
) -> dict[str, Any]:
    """Build a bounded graph-grounded context payload for the Writer.

    The returned structure uses canonical graph state and document metadata only.
    It intentionally excludes raw document text so the Writer remains grounded in
    extracted graph structure and provenance rather than snippet concatenation.
    """
    normalized = validate_state(state)
    graph = state_to_digraph(normalized)

    if graph.number_of_nodes() > 1:
        degree_centrality = nx.degree_centrality(graph)
        density = round(float(nx.density(graph)), 4)
    else:
        degree_centrality = {node: 0.0 for node in graph.nodes}
        density = 0.0

    top_entities = _select_top_entities(
        normalized,
        graph,
        degree_centrality,
        max_entities=max_entities,
    )
    representative_triplets = _select_representative_triplets(
        normalized,
        graph,
        degree_centrality,
        top_entities,
        max_triplets=max_triplets,
    )
    contradictions = _select_contradictions(normalized, max_items=max_contradictions)
    research_gaps = _select_research_gaps(normalized, max_items=max_gaps)
    candidate_pillars = _build_candidate_pillars(
        representative_triplets,
        top_entities,
        max_pillars=max_pillars,
        triplets_per_pillar=triplets_per_pillar,
    )
    document_index = _build_document_index(
        normalized,
        representative_triplets,
        contradictions,
    )

    metrics = dict(normalized.get("metrics", {}))
    metrics.update(
        {
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "density": density,
        }
    )

    return {
        "query": normalized.get("current_query", ""),
        "iteration_count": normalized.get("iteration_count", 0),
        "metrics": metrics,
        "top_entities": top_entities,
        "representative_triplets": representative_triplets,
        "candidate_pillars": candidate_pillars,
        "contradictions": contradictions,
        "research_gaps": research_gaps,
        "document_index": document_index,
        "route_history": list(normalized.get("route_history", []))[-5:],
    }


def _select_top_entities(
    state: Mapping[str, Any],
    graph: nx.DiGraph,
    degree_centrality: Mapping[str, float],
    *,
    max_entities: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for canonical_name, entity in state.get("entities", {}).items():
        disputed = bool(graph.nodes[canonical_name].get("disputed")) if graph.has_node(canonical_name) else False
        rows.append(
            {
                "canonical_name": canonical_name,
                "type": entity.get("type"),
                "description": entity.get("description"),
                "aliases": list(entity.get("aliases", [])),
                "confidence": entity.get("confidence"),
                "source_document_ids": list(entity.get("source_document_ids", [])),
                "evidence_refs": list(entity.get("evidence_refs", [])),
                "degree": graph.degree(canonical_name) if graph.has_node(canonical_name) else 0,
                "degree_centrality": round(float(degree_centrality.get(canonical_name, 0.0)), 4),
                "disputed": disputed,
            }
        )

    rows.sort(
        key=lambda item: (
            -int(item["disputed"]),
            -int(item["degree"]),
            -float(item["degree_centrality"]),
            -float(item["confidence"] or 0.0),
            -len(item["source_document_ids"]),
            str(item["canonical_name"]).lower(),
        )
    )
    return rows[:max_entities]


def _select_representative_triplets(
    state: Mapping[str, Any],
    graph: nx.DiGraph,
    degree_centrality: Mapping[str, float],
    top_entities: list[dict[str, Any]],
    *,
    max_triplets: int,
) -> list[dict[str, Any]]:
    top_entity_names = {entity["canonical_name"] for entity in top_entities}
    scored: list[tuple[tuple[float, ...], dict[str, Any]]] = []

    for triplet in state.get("triplets", []):
        subject = str(triplet.get("subject", ""))
        obj = str(triplet.get("object", ""))
        confidence = float(triplet.get("confidence") or 0.0)
        subject_degree = graph.degree(subject) if graph.has_node(subject) else 0
        object_degree = graph.degree(obj) if graph.has_node(obj) else 0
        subject_centrality = float(degree_centrality.get(subject, 0.0))
        object_centrality = float(degree_centrality.get(obj, 0.0))
        score = (
            float(subject in top_entity_names),
            float(obj in top_entity_names),
            confidence,
            float(subject_degree + object_degree),
            subject_centrality + object_centrality,
            float(triplet.get("extraction_iteration", 0)),
        )
        scored.append(
            (
                score,
                {
                    "triplet_id": triplet.get("triplet_id"),
                    "subject": subject,
                    "predicate": triplet.get("predicate"),
                    "object": obj,
                    "statement": _triplet_statement(triplet),
                    "evidence": triplet.get("evidence"),
                    "source_document_id": triplet.get("source_document_id"),
                    "source_url": triplet.get("source_url"),
                    "confidence": triplet.get("confidence"),
                    "extraction_iteration": triplet.get("extraction_iteration", 0),
                    "subject_degree": subject_degree,
                    "object_degree": object_degree,
                },
            )
        )

    scored.sort(
        key=lambda item: (
            -item[0][0],
            -item[0][1],
            -item[0][2],
            -item[0][3],
            -item[0][4],
            -item[0][5],
            str(item[1]["triplet_id"]),
        )
    )
    return [payload for _, payload in scored[:max_triplets]]


def _build_candidate_pillars(
    representative_triplets: list[dict[str, Any]],
    top_entities: list[dict[str, Any]],
    *,
    max_pillars: int,
    triplets_per_pillar: int,
) -> list[dict[str, Any]]:
    triplets_by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for triplet in representative_triplets:
        triplets_by_entity[str(triplet["subject"])].append(triplet)
        if triplet["object"] != triplet["subject"]:
            triplets_by_entity[str(triplet["object"])].append(triplet)

    pillars: list[dict[str, Any]] = []
    used_triplet_ids: set[str] = set()
    for entity in top_entities:
        entity_name = str(entity["canonical_name"])
        candidates = [
            triplet
            for triplet in triplets_by_entity.get(entity_name, [])
            if str(triplet["triplet_id"]) not in used_triplet_ids
        ]
        if not candidates:
            continue

        selected = candidates[:triplets_per_pillar]
        used_triplet_ids.update(str(triplet["triplet_id"]) for triplet in selected)
        predicate_hints = list(dict.fromkeys(str(triplet["predicate"]) for triplet in selected))
        title_hint = entity_name
        if predicate_hints:
            title_hint = f"{entity_name} - {', '.join(predicate_hints[:2])}"

        pillars.append(
            {
                "anchor_entity": entity_name,
                "title_hint": title_hint,
                "predicate_hints": predicate_hints[:3],
                "triplet_ids": [str(triplet["triplet_id"]) for triplet in selected],
                "triplets": selected,
            }
        )

        if len(pillars) >= max_pillars:
            break

    if not pillars and representative_triplets:
        selected = representative_triplets[:triplets_per_pillar]
        pillars.append(
            {
                "anchor_entity": str(selected[0]["subject"]),
                "title_hint": "Primary graph relationships",
                "predicate_hints": list(
                    dict.fromkeys(str(triplet["predicate"]) for triplet in selected)
                )[:3],
                "triplet_ids": [str(triplet["triplet_id"]) for triplet in selected],
                "triplets": selected,
            }
        )

    return pillars


def _select_contradictions(
    state: Mapping[str, Any],
    *,
    max_items: int,
) -> list[dict[str, Any]]:
    rows = [dict(item) for item in state.get("contradictions", [])]
    severity_order = {"high": 0, "low": 1}
    status_order = {
        "open": 0,
        "investigating": 1,
        "accepted_uncertainty": 2,
        "resolved": 3,
    }
    rows.sort(
        key=lambda item: (
            status_order.get(str(item.get("status", "")), 99),
            severity_order.get(str(item.get("severity", "")), 99),
            str(item.get("topic", "")).lower(),
            str(item.get("contradiction_id", "")),
        )
    )
    return rows[:max_items]


def _select_research_gaps(
    state: Mapping[str, Any],
    *,
    max_items: int,
) -> list[dict[str, Any]]:
    rows = [dict(item) for item in state.get("research_gaps", [])]
    priority_order = {"high": 0, "medium": 1, "low": 2}
    status_order = {"open": 0, "investigating": 1, "resolved": 2}
    rows.sort(
        key=lambda item: (
            status_order.get(str(item.get("status", "")), 99),
            priority_order.get(str(item.get("priority", "")), 99),
            int(item.get("created_iteration", 0)),
            str(item.get("gap_id", "")),
        )
    )
    return rows[:max_items]


def _build_document_index(
    state: Mapping[str, Any],
    representative_triplets: list[dict[str, Any]],
    contradictions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    referenced_ids: set[str] = {
        str(triplet["source_document_id"])
        for triplet in representative_triplets
        if triplet.get("source_document_id")
    }
    for contradiction in contradictions:
        for key in ("source_document_id_a", "source_document_id_b"):
            value = contradiction.get(key)
            if value:
                referenced_ids.add(str(value))

    indexed: list[dict[str, Any]] = []
    for document in state.get("documents", []):
        document_id = str(document.get("document_id", ""))
        if referenced_ids and document_id not in referenced_ids:
            continue
        indexed.append(
            {
                "document_id": document_id,
                "title": document.get("title"),
                "url": document.get("url"),
                "query": document.get("query"),
                "acquisition_method": document.get("acquisition_method"),
            }
        )
        if len(indexed) >= 10:
            break
    return indexed


def _triplet_statement(triplet: Mapping[str, Any]) -> str:
    subject = str(triplet.get("subject", "")).strip()
    predicate = str(triplet.get("predicate", "")).strip()
    obj = str(triplet.get("object", "")).strip()
    return " ".join(part for part in (subject, predicate, obj) if part).strip()


__all__ = ["prepare_writer_context"]