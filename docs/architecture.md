# Architecture

## Overview

The Sensemaking agent is designed as a hybrid architecture.

- Reused Body: acquisition capabilities adapted from V1
- New Brain: a state-graph orchestration loop built for relational synthesis

The Body is responsible for getting evidence.
The Brain is responsible for deciding what that evidence means, what is missing,
and whether the system should continue searching or synthesize a report.

## Architectural Principles

1. Separate evidence acquisition from interpretation.
2. Keep orchestration state serializable.
3. Make contradiction a first-class routing signal.
4. Preserve evidence provenance at every stage.
5. Finalize only when the graph is informative enough or loop limits are met.

## Major Layers

### 1. Scout layer

This layer adapts V1 capabilities for:

- query execution
- Tavily search and extract
- browser fallback scraping
- normalization of documents
- retry and rate-limit behavior

The Scout layer must not own the global sensemaking state.

### 2. State layer

This layer defines the canonical `ResearchState` shared between nodes.
It tracks documents, graph content, contradictions, gaps, routing history, and
loop-control metadata.

### 3. Analyst layer

This layer turns documents into graph-ready structures:

- entities
- triplets
- evidence
- alias relationships or normalization hints

### 4. Critic layer

This layer compares new material against the current state and decides whether:

- a contradiction has been discovered
- a research gap has been discovered
- the graph remains incomplete in a way that requires another loop

### 5. Router layer

This layer decides the next action using explicit conditions.

Core outcomes:

- continue_research
- resolve_conflict
- resolve_gap
- finalize

### 6. Writer layer

This layer converts the graph and contradiction log into the final narrative.
It should emphasize structure, influence, uncertainty, and strategic gaps.

## Data Flow

```text
Initial Query
   |
   v
Scout
   |
   v
Analyst
   |
   v
Critic
   |
   +--> resolve_conflict --> Scout
   |
   +--> resolve_gap ------> Scout
   |
   +--> continue_research -> Scout
   |
   '--> finalize ---------> Writer
```

## Planned Runtime Stack

- Python 3.10+
- LangGraph for orchestration
- Pydantic for structured outputs
- NetworkX for in-memory graph operations
- Tavily for search and extract
- Playwright as browser fallback
- Ollama or another compatible LLM endpoint

LangGraph is a core runtime dependency for V2.
LangChain may be used selectively later if a narrow need appears, but it should
not become the primary architecture or replace the explicit state-and-router
design defined in this repository.

## Why LangGraph

LangGraph fits the V2 architecture because the system needs:

- explicit state transitions
- additive state updates
- conditional routing
- support for cyclic workflows
- traceable execution paths

V1 already demonstrates strong orchestration discipline, but its primary model is
recursive research and consolidation. V2 needs a stronger graph-centric state
machine with explicit contradiction and gap-driven routing.

The current implementation has already adopted this direction by making the
state and route-decision layers explicit in code before Scout and node wiring.

## Brain vs Body Boundary

### Body responsibilities

- document discovery
- content acquisition
- normalization
- retry and resilience
- acquisition metadata

### Brain responsibilities

- relationship extraction
- contradiction analysis
- gap detection
- routing decisions
- final synthesis

This separation prevents scraping concerns from leaking into the decision logic.

## Persistence Strategy

The initial implementation should keep orchestration state JSON-serializable so
it can be checkpointed and resumed.

Recommended persistence targets:

- state snapshots
- report artifacts
- graph export artifacts
- optional SQLite metadata store

The first implementation can keep the working graph in memory and persist a
serializable representation for recovery.

## Graph Strategy

The V2 knowledge graph is not the same thing as V1's topic graph.

- V1 topic graph: controls breadth-first decomposition of research tasks
- V2 knowledge graph: stores entities, claims, and relationships discovered in
  the evidence base

The knowledge graph should support:

- multi-hop traversal
- centrality analysis
- conflict-aware visualization
- relationship-based synthesis

## Stop Conditions

The router should allow finalization when one or more of the following holds:

1. iteration limit reached
2. graph saturation detected
3. no high-priority conflicts remain and no unresolved critical gaps remain
4. budget limits force graceful completion

The exact decision rules are defined in [sensemaking-loop.md](sensemaking-loop.md).

## Observability Expectations

The implementation should make it easy to inspect:

- route decisions
- graph growth per iteration
- contradiction counts
- gap-resolution attempts
- final unresolved uncertainties

This is important for both debugging and trust.