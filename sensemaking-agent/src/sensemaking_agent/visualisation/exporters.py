from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any, Mapping

import networkx as nx

from ..state import state_to_digraph, validate_state


def export_visualizations(
    state: Mapping[str, Any],
    *,
    output_dir: str | Path,
    title: str | None = None,
) -> dict[str, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    graphml_path = output_path / "graph.graphml"
    dot_path = output_path / "graph.dot"
    html_path = output_path / "graph_viewer.html"

    export_graphml(state, graphml_path)
    export_dot(state, dot_path)
    export_html_viewer(state, html_path, title=title)

    return {
        "graphml": graphml_path,
        "dot": dot_path,
        "html": html_path,
    }


def export_graphml(state: Mapping[str, Any], path: str | Path) -> Path:
    export_graph = _build_export_graph(state)
    path = Path(path)
    nx.write_graphml(export_graph, path)
    return path


def export_dot(state: Mapping[str, Any], path: str | Path) -> Path:
    export_graph = _build_export_graph(state)
    path = Path(path)
    lines = [
        "digraph sensemaking {",
        "  graph [rankdir=LR, splines=true, overlap=false];",
        '  node [shape=ellipse, style="filled", fillcolor="#eaf2ff", color="#234a8a", fontname="Segoe UI"];',
        '  edge [color="#6a7a96", fontname="Segoe UI"];',
    ]

    for node_id, attrs in export_graph.nodes(data=True):
        fill = "#ffd9d0" if attrs.get("disputed") == "true" else "#eaf2ff"
        label = attrs.get("label", node_id)
        lines.append(
            f'  "{_escape_dot(node_id)}" [{_dot_attrs({**attrs, "label": label, "fillcolor": fill})}];'
        )

    for source, target, attrs in export_graph.edges(data=True):
        lines.append(
            f'  "{_escape_dot(source)}" -> "{_escape_dot(target)}" [{_dot_attrs(attrs)}];'
        )

    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def export_html_viewer(
    state: Mapping[str, Any],
    path: str | Path,
    *,
    title: str | None = None,
) -> Path:
    normalized = validate_state(state)
    export_graph = _build_export_graph(normalized)
    layout = _compute_layout(export_graph)
    title_text = title or normalized.get("current_query", "Sensemaking Graph") or "Sensemaking Graph"

    svg_width = 960
    svg_height = 640
    node_markup: list[str] = []
    edge_markup: list[str] = []

    for source, target, attrs in export_graph.edges(data=True):
        sx, sy = layout[source]
        tx, ty = layout[target]
        edge_class = "edge disputed" if attrs.get("disputed") == "true" else "edge"
        label = html.escape(str(attrs.get("label", "")))
        mid_x = (sx + tx) / 2
        mid_y = (sy + ty) / 2
        edge_markup.append(
            f'<line class="{edge_class}" x1="{sx:.1f}" y1="{sy:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" />'
        )
        if label:
            edge_markup.append(
                f'<text class="edge-label" x="{mid_x:.1f}" y="{mid_y:.1f}">{label}</text>'
            )

    for node_id, attrs in export_graph.nodes(data=True):
        x, y = layout[node_id]
        node_class = "node disputed" if attrs.get("disputed") == "true" else "node"
        label = html.escape(str(attrs.get("label", node_id)))
        subtitle = html.escape(str(attrs.get("type", "")))
        node_markup.extend(
            [
                f'<circle class="{node_class}" cx="{x:.1f}" cy="{y:.1f}" r="24" />',
                f'<text class="node-label" x="{x:.1f}" y="{y + 5:.1f}">{label}</text>',
                f'<text class="node-subtitle" x="{x:.1f}" y="{y + 22:.1f}">{subtitle}</text>',
            ]
        )

    contradictions = [item for item in normalized.get("contradictions", []) if item.get("status") != "resolved"]
    gaps = [item for item in normalized.get("research_gaps", []) if item.get("status") != "resolved"]
    metrics = normalized.get("metrics", {})

    html_text = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>{html.escape(str(title_text))}</title>
  <style>
    body {{ font-family: Segoe UI, Helvetica, Arial, sans-serif; margin: 0; background: #f5f7fb; color: #182033; }}
    .page {{ display: grid; grid-template-columns: 2fr 1fr; min-height: 100vh; }}
    .canvas {{ padding: 20px; background: linear-gradient(180deg, #ffffff 0%, #edf3ff 100%); border-right: 1px solid #d6def0; }}
    .panel {{ padding: 24px; overflow: auto; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; }}
    h2 {{ margin: 24px 0 12px; font-size: 18px; }}
    .meta {{ color: #55627a; margin-bottom: 16px; }}
    .legend {{ display: flex; gap: 16px; margin-bottom: 12px; font-size: 13px; color: #55627a; }}
    .legend span::before {{ content: \"\"; display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }}
    .legend .normal::before {{ background: #5a8dee; }}
    .legend .disputed::before {{ background: #d96c5f; }}
    svg {{ width: 100%; height: auto; border: 1px solid #d6def0; border-radius: 16px; background: rgba(255,255,255,0.92); box-shadow: 0 10px 30px rgba(28,48,94,0.08); }}
    .edge {{ stroke: #8492aa; stroke-width: 2; opacity: 0.9; }}
    .edge.disputed {{ stroke: #d96c5f; stroke-width: 2.5; }}
    .edge-label {{ font-size: 11px; fill: #4d5b73; text-anchor: middle; }}
    .node {{ fill: #5a8dee; stroke: #234a8a; stroke-width: 2; }}
    .node.disputed {{ fill: #d96c5f; stroke: #8c2d20; }}
    .node-label {{ font-size: 12px; fill: #ffffff; font-weight: 600; text-anchor: middle; pointer-events: none; }}
    .node-subtitle {{ font-size: 10px; fill: #ffffff; text-anchor: middle; pointer-events: none; }}
    .cards {{ display: grid; grid-template-columns: repeat(2, minmax(120px, 1fr)); gap: 12px; }}
    .card {{ background: #ffffff; border: 1px solid #d6def0; border-radius: 12px; padding: 12px; }}
    .card .label {{ font-size: 12px; color: #55627a; }}
    .card .value {{ font-size: 22px; font-weight: 700; margin-top: 4px; }}
    ul {{ padding-left: 18px; }}
    li {{ margin-bottom: 8px; }}
    .empty {{ color: #6d788c; font-style: italic; }}
  </style>
</head>
<body>
  <div class=\"page\">
    <section class=\"canvas\">
      <h1>{html.escape(str(title_text))}</h1>
      <div class=\"meta\">Interactive-free static viewer for the finalized sensemaking graph. Disputed nodes and edges are highlighted.</div>
      <div class=\"legend\"><span class=\"normal\">Normal node</span><span class=\"disputed\">Disputed node or edge</span></div>
      <svg viewBox=\"0 0 {svg_width} {svg_height}\" role=\"img\" aria-label=\"Sensemaking graph viewer\">
        <defs>
          <marker id=\"arrow\" markerWidth=\"10\" markerHeight=\"10\" refX=\"8\" refY=\"3\" orient=\"auto\">
            <path d=\"M0,0 L0,6 L9,3 z\" fill=\"#8492aa\"></path>
          </marker>
        </defs>
        {''.join(edge_markup)}
        {''.join(node_markup)}
      </svg>
    </section>
    <aside class=\"panel\">
      <div class=\"cards\">
        <div class=\"card\"><div class=\"label\">Entities</div><div class=\"value\">{metrics.get('entity_count', export_graph.number_of_nodes())}</div></div>
        <div class=\"card\"><div class=\"label\">Relationships</div><div class=\"value\">{metrics.get('triplet_count', export_graph.number_of_edges())}</div></div>
        <div class=\"card\"><div class=\"label\">Open Contradictions</div><div class=\"value\">{metrics.get('open_contradiction_count', len(contradictions))}</div></div>
        <div class=\"card\"><div class=\"label\">Open Gaps</div><div class=\"value\">{metrics.get('open_gap_count', len(gaps))}</div></div>
      </div>
      <h2>Open Contradictions</h2>
      {_render_contradictions(contradictions)}
      <h2>Research Gaps</h2>
      {_render_gaps(gaps)}
    </aside>
  </div>
</body>
</html>
"""

    path = Path(path)
    path.write_text(html_text, encoding="utf-8")
    return path


def _build_export_graph(state: Mapping[str, Any]) -> nx.DiGraph:
    graph = state_to_digraph(state)
    export_graph = nx.DiGraph()

    for node_id, attrs in graph.nodes(data=True):
        export_graph.add_node(
            node_id,
            label=str(attrs.get("canonical_name") or node_id),
            type=str(attrs.get("type") or ""),
            description=str(attrs.get("description") or ""),
            confidence=_scalar_float(attrs.get("confidence")),
            disputed="true" if bool(attrs.get("disputed")) else "false",
            alias_count=int(len(attrs.get("aliases", []))),
            evidence_ref_count=int(len(attrs.get("evidence_refs", []))),
            source_document_count=int(len(attrs.get("source_document_ids", []))),
        )

    for source, target, attrs in graph.edges(data=True):
        triplets = list(attrs.get("triplets", []))
        predicates = [str(value) for value in attrs.get("predicates", [])]
        disputed = bool(export_graph.nodes[source].get("disputed") == "true" or export_graph.nodes[target].get("disputed") == "true")
        export_graph.add_edge(
            source,
            target,
            label=" | ".join(predicates),
            predicates=";".join(predicates),
            predicate_count=len(predicates),
            weight=int(attrs.get("weight", len(triplets) or 1)),
            disputed="true" if disputed else "false",
            triplet_ids=";".join(str(item.get("triplet_id", "")) for item in triplets if item.get("triplet_id")),
            source_document_ids=";".join(
                str(item.get("source_document_id", ""))
                for item in triplets
                if item.get("source_document_id")
            ),
        )

    return export_graph


def _compute_layout(graph: nx.DiGraph) -> dict[str, tuple[float, float]]:
    if graph.number_of_nodes() == 0:
        return {}
    if graph.number_of_nodes() == 1:
        node = next(iter(graph.nodes))
        return {node: (480.0, 320.0)}

    degrees = sorted(graph.degree, key=lambda item: (-item[1], str(item[0]).lower()))
    anchor_node = degrees[0][0]
    remaining_nodes = [node for node, _ in degrees[1:]]

    layout: dict[str, tuple[float, float]] = {anchor_node: (480.0, 320.0)}
    if not remaining_nodes:
        return layout

    radius = 220.0 if len(remaining_nodes) <= 6 else 260.0
    step = (2 * math.pi) / len(remaining_nodes)
    for index, node_id in enumerate(remaining_nodes):
        angle = -math.pi / 2 + index * step
        x = 480.0 + radius * math.cos(angle)
        y = 320.0 + radius * math.sin(angle)
        layout[node_id] = (x, y)

    return layout


def _render_contradictions(items: list[Mapping[str, Any]]) -> str:
    if not items:
        return '<div class="empty">No unresolved contradictions.</div>'

    lines = ["<ul>"]
    for item in items[:8]:
        lines.append(
            "<li><strong>{topic}</strong> ({severity}, {status})<br />{claim_a}<br />vs<br />{claim_b}</li>".format(
                topic=html.escape(str(item.get("topic", "Untitled dispute"))),
                severity=html.escape(str(item.get("severity", "low"))),
                status=html.escape(str(item.get("status", "open"))),
                claim_a=html.escape(str(item.get("claim_a", ""))),
                claim_b=html.escape(str(item.get("claim_b", ""))),
            )
        )
    lines.append("</ul>")
    return "".join(lines)


def _render_gaps(items: list[Mapping[str, Any]]) -> str:
    if not items:
        return '<div class="empty">No unresolved research gaps.</div>'

    lines = ["<ul>"]
    for item in items[:8]:
        lines.append(
            "<li><strong>{priority}</strong> - {question}<br />Trigger: {trigger}</li>".format(
                priority=html.escape(str(item.get("priority", "medium"))),
                question=html.escape(str(item.get("question", ""))),
                trigger=html.escape(str(item.get("trigger", "unknown"))),
            )
        )
    lines.append("</ul>")
    return "".join(lines)


def _dot_attrs(attrs: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key, value in attrs.items():
        text = str(value)
        parts.append(f'{key}="{_escape_dot(text)}"')
    return ", ".join(parts)


def _escape_dot(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"')


def _scalar_float(value: Any) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "export_dot",
    "export_graphml",
    "export_html_viewer",
    "export_visualizations",
]