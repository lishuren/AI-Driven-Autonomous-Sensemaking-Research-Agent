# Report Specification

## Purpose

This document defines the output contract for the final Sensemaking report.

The report is not a generic summary.
It is a graph-grounded interpretation of the topic, including its major
relationships, points of leverage, disputes, and open questions.

## Output Principles

1. Every major claim should be traceable to graph evidence.
2. Contradictions should be visible, not buried.
3. The narrative should explain relationships, not just facts.
4. Strategic gaps should remain explicit when unresolved.

## Required Sections

### 1. Executive Summary

A concise bottom-line-up-front overview.

Expected qualities:

- 3 to 5 sentences
- identifies the dominant mechanism or pattern
- indicates where uncertainty still matters

### 2. Knowledge Map

Describe the most important relationships in the graph.

Expected content:

- highly connected entities
- bottlenecks, drivers, dependencies, or inhibitors
- the most informative cross-document links

### 3. Key Pillars

Group related parts of the graph into thematic sections.

Expected content:

- 3 to 5 themes
- each theme grounded in clusters of triplets
- explanation of why each theme matters to the overall topic

### 4. Disputed Facts

Explicitly list meaningful contradictions.

Expected content:

- topic of dispute
- competing claims
- severity
- why sources may disagree
- whether the contradiction was resolved, partially resolved, or remains open

### 5. Strategic Gaps

List important unanswered questions or unresolved dependencies.

Expected content:

- open research gaps that affect confidence or completeness
- next investigations that would most improve the graph

### 6. Evidence Trace

Include a traceability-oriented appendix or section summary for important claims.

Expected content:

- source URLs or document identifiers
- representative evidence snippets
- graph references where practical

## Optional Sections

Depending on topic and maturity, the report may also include:

- assumptions and caveats
- timeline or chronology
- graph metrics summary
- recommended next queries

## Tone And Style

The report should:

- use relational verbs such as `drives`, `depends_on`, `blocks`, `amplifies`,
  `competes_with`, or `regulates`
- emphasize explanation over bullet dumping
- avoid false certainty when contradictions remain open
- remain readable to an advanced user without flattening nuance

## Data Sources For The Writer

The Writer should rely primarily on:

- canonical entities
- triplets
- contradiction log
- research gaps
- route history and graph metrics when useful

The Writer should not primarily depend on concatenated raw document text.

## Graph Visualization Readiness

The report should be compatible with future visualization layers.

That means:

- stable identifiers for entities and triplets
- contradiction records that can map to nodes or edges
- thematic pillars that can be associated with graph clusters

## Definition Of A Good Report

A good report helps the user answer:

1. what is connected to what
2. what drives or constrains the system
3. where the strongest evidence sits
4. where sources disagree
5. what remains unresolved and worth investigating next