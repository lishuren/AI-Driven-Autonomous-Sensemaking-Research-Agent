# Sensemaking Loop

## Purpose

This document defines the cyclic routing logic that turns the system from a
one-pass research agent into a sensemaking engine.

## Core Routes

The router should be able to choose between four outcomes:

1. `continue_research`
2. `resolve_conflict`
3. `resolve_gap`
4. `finalize`

## Canonical Flow

```text
Scout -> Analyst -> Critic -> Router

Router:
  - resolve_conflict -> Scout
  - resolve_gap ------> Scout
  - continue_research -> Scout
  - finalize ---------> Writer
```

## Routing Priorities

Suggested priority order:

1. loop safety and budget guardrails
2. unresolved high-severity contradictions
3. unresolved critical research gaps
4. graph saturation / diminishing returns
5. default finalization

## Decision Factors

### 1. Iteration limit

If `iteration_count` exceeds the configured maximum, finalize.

The initial implementation target is a conservative fixed limit, such as 5, to
avoid unbounded loops while the model matures.

### 2. High-severity contradictions

If open high-severity contradictions exist, the router should prefer a targeted
verification pass if safeguards allow.

Expected behavior:

- generate a verification-oriented query
- mark the contradiction as under investigation
- record the route decision in `route_history`

### 3. Research gaps

If unresolved high-priority research gaps exist, the router should send the
state back to Scout with a gap-focused query.

Examples:

- define unexplained term
- clarify prerequisite concept
- verify missing mechanism

### 4. Graph saturation

If the graph is no longer growing meaningfully, finalize.

Suggested initial heuristic:

- if triplet growth in the last iteration is below 10 percent for at least one
  stable cycle, and no high-priority contradictions or gaps remain, finalize

The exact threshold can evolve, but the condition must be explicit.

## Tie-Breaker Search

Tie-breaker search is a special case of conflict resolution.

### Trigger

- at least one open contradiction with `severity == high`

### Goal

- find a more authoritative or clarifying source that can strengthen or weaken
  one side of the conflict

### Safeguards

- limit the number of tie-breaker attempts per contradiction
- record whether a contradiction has already triggered a tie-breaker
- avoid infinite bounce loops between the same conflict and the same query

### Query Guidance

Tie-breaker queries should be more specific than the original topic query.
They should include:

- the disputed entity or metric
- the conflict dimension
- verification language
- preference for authoritative sources when relevant

## Route History

Every route should append an audit record containing:

- iteration
- chosen route
- reason
- target query or contradiction/gap identifier
- timestamp

This is necessary for debugging and trust.

## Example Decision Logic

Illustrative pseudocode:

```python
def should_continue(state: ResearchState) -> str:
    if state["iteration_count"] >= 5:
        return "finalize"

    if has_open_high_severity_conflict(state):
        return "resolve_conflict"

    if has_open_high_priority_gap(state):
        return "resolve_gap"

    if graph_is_stable(state):
        return "finalize"

    return "continue_research"
```

The actual implementation may update `current_query` before returning the route,
or may do so in a dedicated query-generation step.

## Finalization Rules

The system should finalize when:

1. iteration or budget guardrails force a stop
2. no critical contradictions remain unresolved
3. no critical gaps remain unresolved
4. graph growth has flattened enough that further searching is unlikely to add
   meaningfully new structure

Finalization should prefer graceful synthesis over abrupt failure.