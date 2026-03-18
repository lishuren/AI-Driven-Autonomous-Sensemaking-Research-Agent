# Product Requirements Document

## Product Name

AI-Driven Autonomous Sensemaking Research Agent

## Executive Summary

Build an autonomous research system that moves beyond retrieval and summary into
relational synthesis.

The product should build a mental map of a topic by connecting entities,
tracking directional relationships, exposing contradictions, and recursively
resolving missing context before writing the final report.

## Problem Statement

Traditional research agents tend to produce linear outputs:

- what sources said
- what terms appeared most often
- what summary best compresses the available text

That model is useful, but incomplete. Users still need to figure out:

- how claims connect
- which sources disagree
- which concepts are prerequisites for understanding the topic
- where the remaining uncertainty lives

V2 should reduce that burden by making relational synthesis the primary product.

## Product Goals

1. Move from information retrieval to insight generation.
2. Represent topic structure as a knowledge graph that supports multi-hop
   reasoning.
3. Detect and report contradictions instead of masking them.
4. Recursively research gaps in context or terminology.
5. Produce graph-grounded research briefs that explain relationships,
   bottlenecks, and uncertainty.

## Non-Goals

1. Do not optimize first for a polished UI.
2. Do not treat summarization quality alone as the main success metric.
3. Do not implement broad provider abstraction before the core sensemaking loop
   is proven.
4. Do not replicate every V1 feature before the V2 architecture is stable.

## User Value

The user should gain:

- a single connected map instead of many disconnected notes
- explicit disputed facts rather than averaged claims
- automatic exploration of foundational gaps
- a clearer answer to the question, "so what matters here?"

## Functional Requirements

### 1. Relational memory layer

The system must maintain an explicit relational memory composed of:

- canonical entities
- relationship triplets
- evidence references
- source provenance

The relational memory must support cross-document linkage and export to a graph
representation suitable for analysis and visualization.

### 2. Analyst extraction

For each batch of source documents, the system must extract:

- entities
- typed or directional relationships
- evidence snippets
- possible alias normalization

Structured output is required.

### 3. Contradiction detection

The system must compare new claims against the current graph state and identify
when claims conflict.

Each contradiction should track:

- the topic or claim dimension
- evidence for both sides
- severity
- resolution status

### 4. Research gap discovery

The system must identify missing context, jargon, and foundational concepts that
block good synthesis.

Research gaps should be represented explicitly in state and should be routable
back into new searches.

### 5. Tie-breaker search

If a contradiction is high severity, the system must generate a targeted
verification query and gather additional evidence before finalizing when budget
and loop limits allow.

### 6. State-graph orchestration

The workflow must be cyclic and decision-based, not just linear.

The router should be able to:

- continue exploration
- resolve a contradiction
- resolve a research gap
- finalize the report

### 7. Graph-grounded reporting

The final report must be generated from graph state and contradiction state.
It must not be based only on concatenated raw text.

Required report sections are defined in [report-spec.md](report-spec.md).

## Architectural Direction

V2 uses a hybrid architecture.

- Reuse from V1: search and scraping logic, reliability patterns, prompt-file
  organization, and budget-aware behavior.
- New in V2: state graph orchestration, relational memory, contradiction-aware
  routing, and graph-grounded synthesis.

LangGraph is the target orchestration model for the initial Python build.

## Success Criteria

The first implementation should be considered successful when it can:

1. gather documents for an initial query
2. extract a usable graph of entities and triplets
3. record at least one contradiction when sources disagree
4. trigger at least one recursive gap-resolution search when appropriate
5. produce a report that cites graph structure and disputed facts

## Risks

1. Over-copying V1 architecture and losing the sensemaking goal.
2. Over-complicating the graph model before the initial loop works.
3. Treating contradiction detection as an afterthought instead of a routing input.
4. Generating reports from raw snippets because it is easier than graph grounding.

## Delivery Strategy

Implementation should proceed in phases:

1. docs and contracts
2. Scout tool reuse and normalization
3. state model and graph helpers
4. Analyst and Critic nodes
5. LangGraph router
6. Writer and report generation
7. persistence and graph visualization