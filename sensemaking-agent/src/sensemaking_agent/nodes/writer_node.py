"""Writer node for the sensemaking LangGraph workflow.

Synthesizes a final Markdown report from the knowledge graph and contradiction
log.  Uses an LLM guided by the ``writer_synthesize.md`` prompt to produce
structured JSON output, which is rendered into Markdown sections.  Falls back
to a deterministic report when the LLM is unavailable or returns malformed
output.

Returns:
  ``final_synthesis`` — Markdown report string covering: Executive Summary,
      Knowledge Map, Key Pillars, Disputed Facts, Strategic Gaps, and an
      Evidence Trace linking claims to triplet and document provenance.
"""

from __future__ import annotations

import json
import logging
from string import Template
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import LLMConfig
from ..llm_client import generate_text
from ..prompt_loader import load_prompt
from ..state import ResearchState, merge_state, validate_state
from ..synthesis import prepare_writer_context

if TYPE_CHECKING:
    from ..database import RunArtifactStore

logger = logging.getLogger(__name__)

_PROMPT_NAME = "writer_synthesize.md"


class KnowledgeMapItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    insight: str
    supporting_triplet_ids: list[str]


class KeyPillar(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    summary: str
    triplet_ids: list[str]


class DisputedFact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic: str
    claim_a: str
    claim_b: str
    severity: str
    status: str
    explanation: str
    contradiction_id: str | None = None


class StrategicGap(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str
    priority: str
    status: str
    why_it_matters: str
    gap_id: str | None = None


class EvidenceTraceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claim: str
    triplet_ids: list[str] = Field(default_factory=list)
    contradiction_ids: list[str] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)


class WriterOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    executive_summary: str
    knowledge_map: list[KnowledgeMapItem]
    key_pillars: list[KeyPillar]
    disputed_facts: list[DisputedFact]
    strategic_gaps: list[StrategicGap]
    evidence_trace: list[EvidenceTraceItem]


def _parse_writer_output(text: str) -> WriterOutput | None:
    candidates = [text.strip()]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            raw = json.loads(candidate)
            return WriterOutput.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, ValueError):
            continue

    logger.warning(
        "Writer: could not parse LLM response (first 300 chars): %r",
        text[:300],
    )
    return None


def _build_fallback_writer_output(
    query: str,
    context: dict[str, Any],
) -> WriterOutput:
    metrics = context.get("metrics", {})
    top_entities = context.get("top_entities", [])
    triplets = context.get("representative_triplets", [])
    contradictions = context.get("contradictions", [])
    research_gaps = context.get("research_gaps", [])
    candidate_pillars = context.get("candidate_pillars", [])

    top_entity_names = [entity["canonical_name"] for entity in top_entities[:3]]
    contradiction_count = len(contradictions)
    gap_count = len(research_gaps)

    if triplets:
        dominant_statement = triplets[0]["statement"]
        summary_sentences = [
            f"The current graph for '{query}' is organized around {dominant_statement}.",
            f"It currently captures {metrics.get('triplet_count', len(triplets))} triplets across {metrics.get('entity_count', len(top_entities))} entities.",
        ]
        if top_entity_names:
            summary_sentences.append(
                f"The most connected entities are {', '.join(top_entity_names)}."
            )
    else:
        summary_sentences = [
            f"The current run for '{query}' has not produced enough graph relationships for a full synthesis.",
            f"It currently has {metrics.get('entity_count', len(top_entities))} entities and {metrics.get('triplet_count', len(triplets))} triplets.",
        ]

    if contradiction_count:
        summary_sentences.append(
            f"There {'is' if contradiction_count == 1 else 'are'} {contradiction_count} open contradiction{'s' if contradiction_count != 1 else ''} that remain explicit in the report."
        )
    if gap_count:
        summary_sentences.append(
            f"There {'is' if gap_count == 1 else 'are'} {gap_count} strategic gap{'s' if gap_count != 1 else ''} still affecting confidence or completeness."
        )
    if not contradiction_count and not gap_count:
        summary_sentences.append(
            "No unresolved contradictions or strategic gaps are currently recorded in the final state."
        )

    knowledge_map = [
        KnowledgeMapItem(
            insight=str(triplet["statement"]),
            supporting_triplet_ids=[str(triplet["triplet_id"])],
        )
        for triplet in triplets[:5]
    ]

    key_pillars = [
        KeyPillar(
            title=str(pillar["title_hint"]),
            summary="Key relationships: "
            + "; ".join(
                str(triplet["statement"]) for triplet in pillar.get("triplets", [])[:3]
            )
            + ".",
            triplet_ids=[str(value) for value in pillar.get("triplet_ids", [])],
        )
        for pillar in candidate_pillars[:5]
    ]

    disputed_facts = [
        DisputedFact(
            topic=str(item.get("topic", "Disputed topic")),
            claim_a=str(item.get("claim_a", "")),
            claim_b=str(item.get("claim_b", "")),
            severity=str(item.get("severity", "low")),
            status=str(item.get("status", "open")),
            explanation=str(
                item.get("resolution_notes")
                or "The current graph preserves both claims and does not yet collapse the dispute into a single narrative."
            ),
            contradiction_id=(
                str(item["contradiction_id"])
                if item.get("contradiction_id")
                else None
            ),
        )
        for item in contradictions[:5]
    ]

    strategic_gaps = [
        StrategicGap(
            question=str(item.get("question", "")),
            priority=str(item.get("priority", "medium")),
            status=str(item.get("status", "open")),
            why_it_matters=f"Triggered by {item.get('trigger', 'missing context')} and still unresolved in the current state.",
            gap_id=str(item["gap_id"]) if item.get("gap_id") else None,
        )
        for item in research_gaps[:5]
    ]

    evidence_trace = [
        EvidenceTraceItem(
            claim=str(triplet["statement"]),
            triplet_ids=[str(triplet["triplet_id"])],
            contradiction_ids=[],
            source_document_ids=(
                [str(triplet["source_document_id"])]
                if triplet.get("source_document_id")
                else []
            ),
            source_urls=(
                [str(triplet["source_url"])] if triplet.get("source_url") else []
            ),
        )
        for triplet in triplets[:5]
    ]

    return WriterOutput(
        executive_summary=" ".join(summary_sentences[:4]).strip(),
        knowledge_map=knowledge_map,
        key_pillars=key_pillars,
        disputed_facts=disputed_facts,
        strategic_gaps=strategic_gaps,
        evidence_trace=evidence_trace,
    )


def _render_markdown(query: str, output: WriterOutput) -> str:
    title = query.strip() or "Research Report"
    lines: list[str] = [f"# {title}", "", "## Executive Summary", "", output.executive_summary.strip(), ""]

    lines.extend(["## Knowledge Map", ""])
    if output.knowledge_map:
        for item in output.knowledge_map:
            line = f"- {item.insight.strip()}"
            if item.supporting_triplet_ids:
                line += f" [Triplets: {', '.join(item.supporting_triplet_ids)}]"
            lines.append(line)
    else:
        lines.append("- No high-salience graph relationships were available for synthesis.")
    lines.append("")

    lines.extend(["## Key Pillars", ""])
    if output.key_pillars:
        for pillar in output.key_pillars:
            lines.extend([f"### {pillar.title.strip()}", "", pillar.summary.strip()])
            if pillar.triplet_ids:
                lines.append(f"Evidence: {', '.join(pillar.triplet_ids)}")
            lines.append("")
    else:
        lines.append("- No stable thematic pillars were available in the current graph.")
        lines.append("")

    lines.extend(["## Disputed Facts", ""])
    if output.disputed_facts:
        for fact in output.disputed_facts:
            lines.extend(
                [
                    f"### {fact.topic.strip()}",
                    "",
                    f"- Claim A: {fact.claim_a.strip()}",
                    f"- Claim B: {fact.claim_b.strip()}",
                    f"- Severity: {fact.severity.strip()}",
                    f"- Status: {fact.status.strip()}",
                    f"- Interpretation: {fact.explanation.strip()}",
                ]
            )
            if fact.contradiction_id:
                lines.append(f"- Contradiction ID: {fact.contradiction_id.strip()}")
            lines.append("")
    else:
        lines.append("- No material contradictions are currently recorded.")
        lines.append("")

    lines.extend(["## Strategic Gaps", ""])
    if output.strategic_gaps:
        for gap in output.strategic_gaps:
            lines.append(
                f"- [{gap.priority.strip()} | {gap.status.strip()}] {gap.question.strip()}"
            )
            lines.append(f"  Why it matters: {gap.why_it_matters.strip()}")
            if gap.gap_id:
                lines.append(f"  Gap ID: {gap.gap_id.strip()}")
    else:
        lines.append("- No unresolved strategic gaps are currently recorded.")
    lines.append("")

    lines.extend(["## Evidence Trace", ""])
    if output.evidence_trace:
        for item in output.evidence_trace:
            lines.extend([f"### {item.claim.strip()}", ""])
            if item.triplet_ids:
                lines.append(f"- Triplets: {', '.join(item.triplet_ids)}")
            if item.contradiction_ids:
                lines.append(f"- Contradictions: {', '.join(item.contradiction_ids)}")
            if item.source_document_ids:
                lines.append(f"- Documents: {', '.join(item.source_document_ids)}")
            if item.source_urls:
                lines.append(f"- Sources: {', '.join(_format_source_links(item.source_urls))}")
            lines.append("")
    else:
        lines.append("- No evidence trace items were available.")

    return "\n".join(lines).strip() + "\n"


def _format_source_links(urls: list[str]) -> list[str]:
    links: list[str] = []
    for index, url in enumerate(urls, start=1):
        clean = url.strip()
        if not clean:
            continue
        links.append(f"[Source {index}]({clean})")
    return links


def make_writer_node(
    llm_config: LLMConfig | None = None,
    artifact_store: RunArtifactStore | None = None,
    prompt_dir: str | None = None,
):
    _config = llm_config or LLMConfig()

    try:
        _prompt_template = load_prompt(_PROMPT_NAME, prompt_dir)
    except FileNotFoundError:
        logger.error(
            "Writer prompt %r not found — using deterministic fallback output.",
            _PROMPT_NAME,
        )
        _prompt_template = None

    async def _writer_node(state: ResearchState) -> dict[str, Any]:
        """Generate a graph-grounded Markdown report from the current state."""
        normalized = validate_state(state)
        query = normalized.get("current_query", "")
        context = prepare_writer_context(normalized)

        writer_output: WriterOutput | None = None
        used_llm = False

        if _prompt_template and context.get("representative_triplets"):
            raw_user_prompt = (normalized.get("user_prompt") or "").strip()
            user_context = (
                f"\n## Additional Research Context\n\n{raw_user_prompt}\n"
                if raw_user_prompt
                else ""
            )
            prompt = Template(_prompt_template).safe_substitute(
                query=query,
                context_json=json.dumps(context, indent=2, ensure_ascii=False),
                user_context=user_context,
            )
            raw_text = await generate_text(
                prompt=prompt,
                model=_config.model,
                base_url=_config.base_url,
                provider=_config.provider,
                api_key=_config.api_key,
                timeout=_config.timeout,
            )

            if raw_text:
                writer_output = _parse_writer_output(raw_text)
                used_llm = writer_output is not None

        if writer_output is None:
            writer_output = _build_fallback_writer_output(query, context)

        markdown = _render_markdown(query, writer_output)

        logger.info(
            "Writer node: synthesized final report for query %r using %s context.",
            query,
            "LLM" if used_llm else "deterministic fallback",
        )

        final_state = merge_state(normalized, final_synthesis=markdown)

        if artifact_store is not None:
            artifact_store.save_final(final_state)

        return {"final_synthesis": markdown}

    return _writer_node


async def writer_node(state: ResearchState) -> dict[str, Any]:
    return await make_writer_node()(state)
