# Implementation Plan

## Goal

Translate the Sensemaking architecture from documentation into a stable,
incrementally buildable codebase without drifting back into a linear RAG design.

## Phase 1: Documentation Lock

Deliverables:

1. root README
2. contributor guide
3. Copilot instructions
4. PRD
5. architecture and state docs
6. workflow, reporting, and reuse-boundary docs

Exit criteria:

- contributors can identify the intended state model
- contributors can identify the node responsibilities
- contributors can identify what can and cannot be reused from V1

## Phase 2: Repository Scaffolding

Status: in progress, largely complete for the initial foundation.

Deliverables:

1. Python package layout under `sensemaking-agent/`
2. `pyproject.toml` or equivalent project configuration
3. prompt directory structure
4. test directory structure
5. baseline lint and test tooling

Exit criteria:

- package layout matches the architecture docs
- contributors can start implementing nodes without restructuring the repo first

Current progress:

- `sensemaking-agent/` exists
- package metadata exists
- test layout exists
- baseline state and routing tests exist

## Phase 3: Scout Extraction

Deliverables:

1. normalized Scout tool interface
2. Tavily search integration
3. Tavily extract support
4. Playwright fallback scraping
5. acquisition metadata and error handling

Reference source:

- AI-Driven-Autonomous-Research-Agent search and scraper tooling

Exit criteria:

- Scout returns normalized documents independent of orchestration state
- V1-derived logic is adapted without copying V1 architecture wholesale

## Phase 4: State And Graph Model

Status: in progress, initial foundation implemented.

Deliverables:

1. `ResearchState`
2. entity and triplet schemas
3. contradiction and gap schemas
4. NetworkX export helpers
5. serialization helpers

Exit criteria:

- the graph is append-friendly
- the state can be checkpointed
- tests validate merge and serialization behavior

Current progress:

- `ResearchState` and related records are implemented
- merge and validation helpers are implemented
- NetworkX export helper is implemented
- baseline tests exist for state and graph behavior

## Phase 5: Analyst And Critic Nodes

Deliverables:

1. Analyst extraction node
2. Critic contradiction and gap node
3. structured output models
4. prompt files for extraction and review

Exit criteria:

- new documents can grow the graph
- contradictions are logged rather than overwritten
- research gaps become routable state

## Phase 6: LangGraph Orchestration

Status: started at the router layer only.

Deliverables:

1. graph builder
2. routing function
3. tie-breaker query generation
4. iteration guardrails
5. route-history tracking

Exit criteria:

- the workflow can loop safely
- route decisions are testable and explainable

Current progress:

- route-decision logic is implemented
- route-history updates are implemented
- full LangGraph node wiring is not yet implemented

## Validation Note

Editor-level validation is currently clean for the implemented Python files.
Full test execution still requires a working Python interpreter in the runtime
environment.

## Phase 7: Writer And Reporting

Deliverables:

1. Writer node
2. graph-grounded report generator
3. contradiction and strategic-gap sections
4. report persistence

Exit criteria:

- the final report is generated from graph state
- unresolved disputes appear explicitly in the output

## Phase 8: Visualization And Persistence

Deliverables:

1. graph export artifact
2. optional HTML or notebook-based visualization
3. checkpointing and resume support
4. observability hooks for graph growth and route decisions

Exit criteria:

- contributors can inspect graph structure and unresolved contradictions
- long-running sessions can recover without losing meaningfully accumulated state

## Cross-Cutting Rules

1. Do not modify V1 while building V2.
2. Keep V1 reuse at the tool and pattern level unless the docs explicitly permit
   more.
3. Favor explicit schemas over implicit dicts where possible.
4. Keep the report contract aligned with the graph contract.
5. Update docs when implementation forces a contract change.