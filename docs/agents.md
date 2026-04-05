# Agents

## Overview

The core V2 runtime is organized around four agent roles:

1. Scout
2. Analyst
3. Critic
4. Writer

These are not independent products. They are specialized steps in a shared
state-graph workflow.

## Scout

### Purpose

Acquire and normalize source material for the current query.

### Inputs

- `current_query`
- optional routing hints from contradictions or research gaps
- budget and acquisition configuration
- optional GraphRAG index directory for local corpus querying

### Outputs

- normalized documents appended to `documents`
- acquisition metadata for provenance and debugging

### Responsibilities

- perform search using V1-derived patterns
- use extract or scrape fallbacks when needed
- query a pre-built GraphRAG index when available, merging local corpus results
  with web search results
- normalize documents into a stable schema
- avoid direct knowledge-graph logic

### Must Not Do

- update contradictions directly
- perform graph reasoning
- synthesize the final report

## Analyst

### Purpose

Transform raw documents into graph-ready structures.

### Inputs

- latest documents
- optional prior entity registry for alias normalization
- prompt guidance for structured extraction

### Outputs

- new or updated entities
- new triplets with evidence and provenance

### Responsibilities

- identify specific entities
- extract directional relationships
- preserve source evidence
- normalize aliases where defensible
- prefer structured output contracts

### Must Not Do

- silently discard uncertain evidence
- overwrite prior graph state destructively
- decide final routing outcomes on its own

## Critic

### Purpose

Evaluate new graph material against existing state to detect contradiction,
uncertainty, and missing context.

### Inputs

- current entity and triplet state
- newly extracted triplets
- optional prior contradictions and unresolved gaps

### Outputs

- contradiction records
- research-gap records
- optional routing hints or priority annotations

### Responsibilities

- compare competing claims
- assess conflict severity
- identify missing prerequisites or ambiguous mechanisms
- preserve both sides of a dispute when disagreement exists

### Must Not Do

- resolve conflict by averaging claims together
- erase older evidence because a newer source looks cleaner
- write the final narrative

## Writer

### Purpose

Generate the final synthesis from graph state.

### Inputs

- entity registry
- triplets
- contradiction log
- unresolved research gaps
- optional graph metrics

### Outputs

- `final_synthesis`
- optional structured report sections before rendering

### Responsibilities

- interpret the graph rather than summarizing raw snippets
- explain major relationships and bottlenecks
- present disputed facts and unresolved uncertainty clearly
- recommend next questions or strategic gaps

### Must Not Do

- hallucinate claims absent from graph evidence
- suppress contradictions for readability
- rewrite the evidence base into a falsely unified story

## Shared Contract Rules

All nodes should follow these rules:

1. preserve provenance
2. prefer structured outputs over free-form strings
3. avoid destructive overwrites
4. keep state JSON-serializable at workflow boundaries
5. add enough metadata for downstream debugging and reporting

## Suggested Prompt Files

The first implementation should likely separate prompt files for:

- Scout query rewriting or tie-breaker generation
- Analyst extraction
- Critic contradiction and gap detection
- Writer synthesis

Prompt files should remain aligned with the contracts defined here.