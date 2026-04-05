# Reuse From V1

## Purpose

This document defines what V2 should reuse from
AI-Driven-Autonomous-Research-Agent and what it should deliberately avoid copying.

The goal is controlled reuse, not architectural duplication.

## Reuse Principles

1. Reuse tool patterns that are already proven.
2. Do not import V1 assumptions that conflict with sensemaking goals.
3. When adapting V1 behavior, keep the V2 interface clean and decoupled.

## Safe Reuse Areas

The following are valid reuse candidates:

### Search and extraction

- Tavily search integration
- Tavily extract integration
- result normalization patterns
- fallback behavior when raw content is insufficient

### Scraping and resilience

- Playwright fallback scraping
- retry and timeout strategies
- user-agent handling
- robots and ethics guidance where still applicable

### LLM plumbing

- async I/O patterns
- prompt-loading patterns
- local or compatible LLM client patterns
- graceful degradation and timeout behavior

### Budget and observability concepts

- query budget controls
- credit tracking concepts
- search logging concepts
- progress checkpoint ideas

## Areas That Must Not Be Copied As The Main V2 Design

### Primary orchestration model

Do not treat V1 Planner -> Researcher -> Critic as the main V2 architecture.

V2 should be designed around Scout, Analyst, Critic, and Writer with routing
based on contradictions, gaps, and graph saturation.

### Primary memory model

Do not use V1 TopicGraph as the V2 knowledge graph.

V1 TopicGraph manages hierarchical research tasks.
V2 needs a graph of entities, claims, relationships, and uncertainties.

### Final report model

Do not use V1 summary-first reporting as the V2 report contract.

V2 reports must be graph-grounded and contradiction-aware.

### Conflict handling

Do not let contradiction remain an implicit quality issue.

In V2 it is an explicit tracked object and a routing input.

## Recommended Adaptation Strategy

### Scout adaptation

Adapt V1 search and scraping into a clean V2 Scout boundary that returns
normalized documents only.

The Scout should not own:

- graph mutation logic
- contradiction logic
- final synthesis logic

### Prompt adaptation

V1 prompt-organization patterns are useful, but V2 prompts should be rewritten to
optimize for extraction, contradiction analysis, and synthesis rather than summary
quality alone.

### Persistence adaptation

V1 checkpointing ideas are useful, but V2 persistence should center on
serializable state snapshots, graph artifacts, and contradiction logs.

## Reference Files In V1

High-value reference points include:

- `research-agent/src/tools/search_tool.py`
- `research-agent/src/tools/scraper_tool.py`
- `research-agent/src/llm_client.py`
- `research-agent/src/prompt_loader.py`
- `research-agent/src/budget.py`

These should inform implementation decisions without dictating the V2 runtime
shape.

## Superseded V1 Patterns

| V1 Component | V2 Replacement | Notes |
|--|--|--|
| `tools/resource_loader.py` (pymupdf, python-docx) | `graphragloader` package | Local file conversion now uses LlamaIndex via graphragloader; GraphRAG index replaces flat file loading as the primary local-corpus strategy |

## Hard Rule

Do not modify AI-Driven-Autonomous-Research-Agent while implementing V2.
Treat it as read-only reference material.