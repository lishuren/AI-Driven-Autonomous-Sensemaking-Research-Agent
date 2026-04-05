"""Critic node for the sensemaking LangGraph workflow.

Compares newly extracted triplets against the existing knowledge graph to
detect contradictions and research gaps.  Only triplets added in the current
iteration are examined (determined by ``extraction_iteration`` matching
``state["iteration_count"]``).

Returns:
  ``contradictions`` — new ``ContradictionState`` dicts (appended via
      ``operator.add`` reducer — never overwrites existing records).
  ``research_gaps``  — new ``ResearchGapState`` dicts (appended likewise).
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

_PROMPT_NAME = "critic_analyze.md"


# ---------------------------------------------------------------------------
# LLM output models
# ---------------------------------------------------------------------------

class ExtractedContradiction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject: str
    topic: str
    claim_a: str
    claim_b: str
    evidence_a: Optional[str] = None
    evidence_b: Optional[str] = None
    severity: str = "low"


class ExtractedGap(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str
    trigger: str
    priority: str = "medium"


class CriticResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contradictions: list[ExtractedContradiction] = Field(default_factory=list)
    research_gaps: list[ExtractedGap] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contradiction_id(subject: str, claim_a: str, claim_b: str) -> str:
    digest = hashlib.sha1(
        f"{subject}::{claim_a}::{claim_b}".encode()
    ).hexdigest()[:16]
    return f"con_{digest}"


def _gap_id(question: str) -> str:
    digest = hashlib.sha1(question.encode()).hexdigest()[:16]
    return f"gap_{digest}"


def _parse_critic_result(text: str) -> Optional[CriticResult]:
    candidates = [text.strip()]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            raw = json.loads(candidate)
            return CriticResult.model_validate(raw)
        except (json.JSONDecodeError, ValidationError, ValueError):
            continue

    logger.warning(
        "Critic: could not parse LLM response (first 300 chars): %r", text[:300]
    )
    return None


def _severity_value(s: str) -> str:
    return s if s in ("low", "high") else "low"


def _priority_value(p: str) -> str:
    return p if p in ("low", "medium", "high") else "medium"


# ---------------------------------------------------------------------------
# Node factory
# ---------------------------------------------------------------------------

def make_critic_node(
    llm_config: Optional[LLMConfig] = None,
    prompt_dir: Optional[str] = None,
):
    """Return a Critic node callable closed over *llm_config*.

    Parameters
    ----------
    llm_config:
        LLM configuration.  A default ``LLMConfig`` is used when omitted.
    prompt_dir:
        Optional path to a custom prompts directory.  When provided, the
        bundled ``critic_analyze.md`` is overridden by the file at
        ``prompt_dir/critic_analyze.md`` if it exists.
    """
    _config = llm_config or LLMConfig()

    try:
        _prompt_template = load_prompt(_PROMPT_NAME, prompt_dir)
    except FileNotFoundError:
        logger.error(
            "Critic prompt %r not found — analysis will be skipped.", _PROMPT_NAME
        )
        _prompt_template = None

    async def critic_node(state: ResearchState) -> dict[str, Any]:
        if not _prompt_template:
            return {}

        iteration = state.get("iteration_count", 0)
        all_triplets: list[dict[str, Any]] = list(state.get("triplets", []))

        # Only analyse triplets extracted this iteration.
        new_triplets = [
            t for t in all_triplets
            if t.get("extraction_iteration") == iteration
        ]

        if not new_triplets:
            logger.debug("Critic: no new triplets to analyse.")
            return {}

        existing_triplets = [
            t for t in all_triplets
            if t.get("extraction_iteration") != iteration
        ]

        # Build sets of existing contradiction / gap IDs to avoid re-recording.
        existing_con_ids: set[str] = {
            c.get("contradiction_id", "")
            for c in state.get("contradictions", [])
        }
        existing_gap_ids: set[str] = {
            g.get("gap_id", "")
            for g in state.get("research_gaps", [])
        }

        # Build user_context section for prompts (from requirements background).
        raw_user_prompt = (state.get("user_prompt") or "").strip()
        user_context = (
            f"\n## Additional Research Context\n\n{raw_user_prompt}\n"
            if raw_user_prompt
            else ""
        )
        raw_constraints = (state.get("constraints") or "").strip()
        constraints = (
            f"\n## Research Constraints\n\n{raw_constraints}\n"
            if raw_constraints
            else ""
        )

        prompt = Template(_prompt_template).safe_substitute(
            query=state.get("current_query", ""),
            iteration=str(iteration),
            triplets_new=json.dumps(new_triplets, ensure_ascii=False),
            triplets_existing=json.dumps(existing_triplets, ensure_ascii=False),
            entities=json.dumps(state.get("entities") or {}, ensure_ascii=False),
            user_context=user_context,
            constraints=constraints,
        )

        logger.debug(
            "Critic: calling LLM with %d new and %d existing triplets.",
            len(new_triplets),
            len(existing_triplets),
        )
        raw_text = await generate_text(
            prompt=prompt,
            model=_config.model,
            base_url=_config.base_url,
            provider=_config.provider,
            api_key=_config.api_key,
            timeout=_config.timeout,
        )

        if not raw_text:
            logger.warning("Critic: LLM returned no content — skipping analysis.")
            return {}

        result = _parse_critic_result(raw_text)
        if result is None:
            return {}

        new_contradictions: list[dict[str, Any]] = []
        for c in result.contradictions:
            if not (c.subject and c.claim_a and c.claim_b):
                continue
            cid = _contradiction_id(c.subject, c.claim_a, c.claim_b)
            if cid in existing_con_ids:
                continue
            existing_con_ids.add(cid)
            new_contradictions.append({
                "contradiction_id": cid,
                "topic": c.topic,
                "claim_a": c.claim_a,
                "claim_b": c.claim_b,
                "evidence_a": c.evidence_a,
                "evidence_b": c.evidence_b,
                "source_document_id_a": None,
                "source_document_id_b": None,
                "severity": _severity_value(c.severity),
                "status": "open",
                "resolution_notes": None,
            })

        new_gaps: list[dict[str, Any]] = []
        for g in result.research_gaps:
            if not g.question:
                continue
            gid = _gap_id(g.question)
            if gid in existing_gap_ids:
                continue
            existing_gap_ids.add(gid)
            new_gaps.append({
                "gap_id": gid,
                "question": g.question,
                "trigger": g.trigger,
                "priority": _priority_value(g.priority),
                "status": "open",
                "created_iteration": iteration,
                "resolved_iteration": None,
            })

        logger.info(
            "Critic: found %d new contradiction(s) and %d new gap(s).",
            len(new_contradictions),
            len(new_gaps),
        )

        update: dict[str, Any] = {}
        if new_contradictions:
            update["contradictions"] = new_contradictions
        if new_gaps:
            update["research_gaps"] = new_gaps
        return update

    return critic_node
