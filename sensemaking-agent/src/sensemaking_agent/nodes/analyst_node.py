"""Analyst node for the sensemaking LangGraph workflow.

Extracts entities and relationship triplets from documents that have not yet
been processed.  Uses an LLM guided by the ``analyst_extract.md`` prompt to
produce structured JSON output, which is parsed into Pydantic models and
merged into the running state.

Only documents whose ``document_id`` does not appear in any existing triplet's
``source_document_id`` are processed — ensuring each document is analysed
exactly once across all iterations.

Returns:
  ``entities``  — full merged entity registry (replaces existing dict).
  ``triplets``  — new triplet dicts (appended via operator.add reducer).
"""

from __future__ import annotations

import hashlib
import json
import logging
from string import Template
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import LLMConfig
from ..llm_client import generate_text
from ..prompt_loader import load_prompt
from ..state import ResearchState

logger = logging.getLogger(__name__)

_PROMPT_NAME = "analyst_extract.md"


# ---------------------------------------------------------------------------
# Extraction output models
# ---------------------------------------------------------------------------

class ExtractedEntity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    canonical_name: str
    type: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    description: Optional[str] = None


class ExtractedTriplet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject: str
    predicate: str
    object: str
    evidence: str
    confidence: Optional[float] = None


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entities: list[ExtractedEntity] = Field(default_factory=list)
    triplets: list[ExtractedTriplet] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _triplet_id(subject: str, predicate: str, obj: str, doc_id: str) -> str:
    """Derive a stable short ID from the triplet's key fields."""
    digest = hashlib.sha1(
        f"{subject}::{predicate}::{obj}::{doc_id}".encode()
    ).hexdigest()[:16]
    return f"trip_{digest}"


def _parse_extraction(text: str) -> Optional[ExtractionResult]:
    """Parse LLM output into an ExtractionResult.

    Tries the raw response first, then searches for the first ``{...}``
    span to handle models that include preamble text before the JSON.
    Returns ``None`` when parsing fails entirely.
    """
    candidates = [text.strip()]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            raw = json.loads(candidate)
            return ExtractionResult.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, ValueError):
            continue

    logger.warning(
        "Analyst: could not parse LLM response (first 300 chars): %r", text[:300]
    )
    return None


def _merge_entity(registry: dict[str, Any], entity: ExtractedEntity, doc_id: str) -> None:
    """Upsert *entity* into *registry* in-place.

    Existing entries are updated additively: new aliases are appended and the
    source document ID is recorded.  Previously stored data is never erased.
    """
    name = entity.canonical_name.strip()
    if not name:
        return

    if name in registry:
        existing = registry[name]
        # Append new aliases (dedup, preserve order).
        seen: set[str] = set(existing.get("aliases", []))
        for alias in entity.aliases:
            if alias and alias not in seen:
                existing.setdefault("aliases", []).append(alias)
                seen.add(alias)
        # Append new source doc ID.
        src_ids: list[str] = existing.get("source_document_ids", [])
        if doc_id and doc_id not in src_ids:
            src_ids.append(doc_id)
            existing["source_document_ids"] = src_ids
        # Back-fill description only when currently absent.
        if not existing.get("description") and entity.description:
            existing["description"] = entity.description
    else:
        registry[name] = {
            "canonical_name": name,
            "type": entity.type,
            "aliases": list(entity.aliases),
            "description": entity.description,
            "evidence_refs": [],
            "source_document_ids": [doc_id] if doc_id else [],
            "confidence": None,
        }


# ---------------------------------------------------------------------------
# Node factory
# ---------------------------------------------------------------------------

def make_analyst_node(
    llm_config: Optional[LLMConfig] = None,
    prompt_dir: Optional[str] = None,
):
    """Return an Analyst node callable closed over *llm_config*.

    Parameters
    ----------
    llm_config:
        LLM configuration.  A default ``LLMConfig`` is used when omitted,
        which targets a local Ollama instance reading ``SENSEMAKING_LLM_*``
        env vars.
    prompt_dir:
        Optional path to a custom prompts directory.  When provided, the
        bundled ``analyst_extract.md`` is overridden by the file at
        ``prompt_dir/analyst_extract.md`` if it exists.
    """
    _config = llm_config or LLMConfig()

    try:
        _prompt_template = load_prompt(_PROMPT_NAME, prompt_dir)
    except FileNotFoundError:
        logger.error(
            "Analyst prompt %r not found — extraction will be skipped.", _PROMPT_NAME
        )
        _prompt_template = None

    async def analyst_node(state: ResearchState) -> dict[str, Any]:
        if not _prompt_template:
            return {}

        # Identify documents not yet referenced by any existing triplet.
        processed_doc_ids: set[str] = {
            t.get("source_document_id", "")
            for t in state.get("triplets", [])
            if t.get("source_document_id")
        }
        new_docs = [
            doc for doc in state.get("documents", [])
            if doc.get("document_id") and doc["document_id"] not in processed_doc_ids
        ]

        if not new_docs:
            logger.debug("Analyst: no new documents to process.")
            return {}

        iteration = state.get("iteration_count", 0)
        merged_entities: dict[str, Any] = dict(state.get("entities") or {})
        new_triplets: list[dict[str, Any]] = []

        # Build user_context section for prompts (from requirements background).
        raw_user_prompt = (state.get("user_prompt") or "").strip()
        user_context = (
            f"\n## Additional Research Context\n\n{raw_user_prompt}\n"
            if raw_user_prompt
            else ""
        )

        for doc in new_docs:
            doc_id = doc.get("document_id", "")
            content = doc.get("content", "")[: _config.max_content_chars]

            prompt = Template(_prompt_template).safe_substitute(
                title=doc.get("title", ""),
                url=doc.get("url", ""),
                query=doc.get("query", ""),
                content=content,
                user_context=user_context,
            )

            logger.debug("Analyst: calling LLM for document %r.", doc_id)
            raw_text = await generate_text(
                prompt=prompt,
                model=_config.model,
                base_url=_config.base_url,
                provider=_config.provider,
                api_key=_config.api_key,
                timeout=_config.timeout,
            )

            if not raw_text:
                logger.warning(
                    "Analyst: LLM returned no content for document %r — skipping.",
                    doc_id,
                )
                continue

            result = _parse_extraction(raw_text)
            if result is None:
                continue

            for entity in result.entities:
                _merge_entity(merged_entities, entity, doc_id)

            for triplet in result.triplets:
                if not (triplet.subject and triplet.predicate and triplet.object):
                    continue
                tid = _triplet_id(triplet.subject, triplet.predicate, triplet.object, doc_id)
                new_triplets.append({
                    "triplet_id": tid,
                    "subject": triplet.subject,
                    "predicate": triplet.predicate,
                    "object": triplet.object,
                    "evidence": triplet.evidence,
                    "source_document_id": doc_id,
                    "source_url": doc.get("url"),
                    "confidence": triplet.confidence,
                    "extraction_iteration": iteration,
                })

            logger.info(
                "Analyst (iter %d): doc %r → %d entities, %d triplets extracted.",
                iteration,
                doc_id,
                len(result.entities),
                len(result.triplets),
            )

        update: dict[str, Any] = {"entities": merged_entities}
        if new_triplets:
            update["triplets"] = new_triplets
        return update

    return analyst_node
