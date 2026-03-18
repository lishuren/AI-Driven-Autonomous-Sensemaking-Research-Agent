# Repository Plan

## Objective

Establish a docs-first foundation for the Sensemaking repository and use that
foundation to guide implementation without drifting into a renamed copy of V1.

## Strategic Direction

This repository is a new product that selectively reuses proven components from
AI-Driven-Autonomous-Research-Agent.

The working principle is:

- reuse V1 for the Body
- build a new Brain for V2

The Body includes search, extraction, scraping, normalization, retry, and budget
patterns.
The Brain includes state-graph orchestration, graph construction,
contradiction-aware routing, recursive gap resolution, and graph-grounded
synthesis.

## Planned Deliverables

### 1. Documentation foundation

Create and maintain these source-of-truth docs:

- `README.md`
- `USER_GUIDE.md`
- `CONTRIBUTING.md`
- `.github/copilot-instructions.md`
- `docs/prd.md`
- `docs/architecture.md`
- `docs/state-schema.md`
- `docs/agents.md`
- `docs/sensemaking-loop.md`
- `docs/report-spec.md`
- `docs/reuse-from-v1.md`
- `docs/implementation-plan.md`

### 2. Repository scaffolding

Create a Python-first repository layout that matches the architecture docs.

### 3. Scout implementation

Adapt V1 search and scraping into a clean V2 tool boundary.

### 4. State and graph implementation

Implement `ResearchState`, graph helpers, and serialization support.

### 5. Node implementation

Implement Scout, Analyst, Critic, and Writer around structured contracts.

### 6. Orchestration implementation

Implement LangGraph routing, tie-breaker search, loop guards, and route history.

### 7. Reporting and visualization

Implement graph-grounded report generation and graph export/visualization.

## Execution Order

1. Lock the documentation set.
2. Scaffold the repository to match the docs.
3. Implement Scout.
4. Implement state and graph helpers.
5. Implement Analyst.
6. Implement Critic.
7. Implement router.
8. Implement Writer.
9. Add persistence.
10. Add visualization.

## Constraints

1. Do not modify AI-Driven-Autonomous-Research-Agent.
2. Do not reuse V1 TopicGraph as the primary V2 memory model.
3. Do not generate a final report from raw snippets alone.
4. Do not hide contradiction by averaging conflicting claims.
5. Do not let implementation outrun the documented contracts.

## Immediate Next Step

The next implementation step after this docs pass is to scaffold the Python
package and baseline project files for the V2 codebase.