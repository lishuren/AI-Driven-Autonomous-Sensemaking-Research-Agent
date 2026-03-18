# GitHub Copilot Instructions

## Project Overview

This repository defines an AI-Driven Autonomous Sensemaking Research Agent.

It is a new product that selectively reuses proven components from
AI-Driven-Autonomous-Research-Agent, but it is not a rename of that project and
must not be implemented as a simple copy of V1.

The core goal is to move from search-and-summarize toward relational synthesis.
The system should connect claims across documents, detect contradiction, surface
uncertainty, and generate a final report by interpreting a knowledge graph.

## Source Of Truth

Before writing or changing code, consult these repository docs:

1. `README.md`
2. `docs/prd.md`
3. `docs/architecture.md`
4. `docs/state-schema.md`
5. `docs/agents.md`
6. `docs/sensemaking-loop.md`
7. `docs/report-spec.md`
8. `docs/reuse-from-v1.md`

If generated code conflicts with those documents, update the docs or ask for a
decision before continuing.

## Product Thesis

The output is not just a summary of documents.
The output is a structured interpretation of relationships between entities,
claims, mechanisms, and uncertainties.

Always optimize for:

- graph-grounded reasoning
- explicit evidence trails
- contradiction visibility
- recursive gap resolution
- clear stopping conditions

## Architecture Summary

The target architecture is a hybrid:

- The Body: reusable search, extract, scrape, normalization, retry, and budget
  patterns adapted from V1.
- The Brain: a new LangGraph-oriented state graph that manages sensemaking,
  contradiction handling, and synthesis.

The intended node model is:

1. Scout
2. Analyst
3. Critic
4. Writer

These nodes do not form a simple one-pass pipeline. The router must be able to
loop back to Scout when gaps or disputes require more evidence.

## Required Design Principles

### 1. Relational over linear

Do not treat summarization as the main job.
The primary extraction target is:

- entities
- triplets
- evidence
- contradiction candidates
- research gaps

Every major design choice should preserve cross-document relationship building.

### 2. State-graph orchestration

Prefer a state graph built around explicit transitions and loop guards.

The routing layer should be able to decide between at least these outcomes:

- continue research
- resolve contradiction
- resolve research gap
- finalize report

### 3. Dialectical reasoning

If two claims conflict, do not average them into a single narrative.
Record the contradiction, preserve evidence for both sides, and trigger a
targeted tie-breaker search when severity is high.

### 4. Recursive discovery

If a document depends on unexplained jargon, prerequisite concepts, or missing
context, record those as research gaps and allow the loop to fetch that missing
context before final synthesis.

### 5. Graph-grounded reporting

The Writer must synthesize from the knowledge graph and contradiction log.
Do not let the final report depend primarily on raw text snippets.

## State Requirements

The canonical orchestration state should be serializable and should model at
least the following:

- `documents`: append-only list of normalized source documents
- `entities`: entity registry keyed by canonical name
- `triplets`: append-only relationship records
- `contradictions`: logged conflicts with severity and evidence
- `research_gaps`: unresolved questions or missing concepts
- `current_query`: active research target
- `iteration_count`: loop guard
- `route_history`: optional audit trail of routing decisions
- `metrics`: optional counters for graph growth and conflict density
- `final_synthesis`: final report output

When using LangGraph, prefer additive merge semantics for append-only lists.

## Agent Responsibilities

### Scout

- Reuse V1 search and scraping ideas where appropriate.
- Return normalized documents with URL, title, content, and acquisition metadata.
- Stay decoupled from higher-level graph logic.

### Analyst

- Extract entities and relationship triplets from raw documents.
- Normalize aliases when possible.
- Preserve evidence snippets and source references.
- Prefer structured output formats.

### Critic

- Compare new claims against existing graph state.
- Detect contradiction with severity.
- Identify research gaps and missing context.
- Avoid destructive overwrites of previously collected evidence.

### Writer

- Generate the final narrative from graph structure, not raw snippets alone.
- Include disputed facts and strategic gaps.
- Make the report traceable to triplets and evidence.

## Reuse Boundaries With V1

You may reuse or adapt patterns from AI-Driven-Autonomous-Research-Agent for:

- Tavily search and extract integration
- Playwright fallback scraping
- async HTTP and LLM client behavior
- prompt-file organization
- budget and retry concepts
- normalization and result filtering

Do not reuse V1 as the main architectural template for:

- the primary memory model
- the final report contract
- contradiction handling policy
- routing logic for recursive sensemaking

The V1 TopicGraph is not the V2 knowledge graph.

## Implementation Preferences

- Use Python 3.10+.
- Use `async` / `await` for I/O-heavy boundaries.
- Prefer Pydantic models or equivalent schema enforcement for LLM outputs.
- Keep prompts in prompt files where practical.
- Use NetworkX for in-memory graph analysis unless a documented persistence need
  justifies a different storage layer.
- Keep persistence formats JSON-serializable at workflow boundaries.

## Prompt Design Requirements

When generating prompts or prompt files:

- bias toward extraction and synthesis, not summary compression
- require explicit evidence in outputs
- require contradiction reporting where relevant
- avoid vague generic entities such as `data`, `technology`, or `market`
- prefer directional predicates such as `drives`, `blocks`, `depends_on`,
  `regulates`, or `competes_with`

## Non-Goals

Do not generate or recommend the following as the primary design:

- a single-pass RAG pipeline with one final summary prompt
- a report based only on concatenated snippets
- silent resolution of conflicting claims
- hard coupling between scraping code and orchestration state
- premature UI-first implementation before state, routing, and report contracts
  are stable

## Build Order

Prefer this order when generating code:

1. tool boundary for Scout
2. state schema and graph helpers
3. Analyst extraction models and node
4. Critic models and node
5. router and LangGraph wiring
6. Writer synthesis
7. persistence and reporting
8. visualization

## Repository Protection Rule

Do not modify AI-Driven-Autonomous-Research-Agent when implementing this repo.
Treat V1 as read-only reference material.