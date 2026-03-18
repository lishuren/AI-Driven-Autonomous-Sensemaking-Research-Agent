# AI-Driven Autonomous Sensemaking Research Agent

An autonomous research system focused on sensemaking rather than summary generation.

This repository is the V2 direction for the research workflow pioneered in
AI-Driven-Autonomous-Research-Agent. It reuses proven search and scraping ideas
from V1, but the core product here is different: the primary output is a
graph-grounded explanation of how entities, claims, and uncertainties relate,
not a linear list of findings.

## Status

This repository is currently in a docs-first foundation phase.

- Product scope, architecture, and contributor workflow are being defined first.
- V1 remains the reference implementation for reusable search and scraping logic.
- V2 implementation should begin only after these docs are accepted as the source
  of truth.

## Product Thesis

V1 is optimized for recursive research and structured reporting.
V2 is optimized for relational synthesis.

The intended shift is:

- From search-and-summarize to graph-grounded sensemaking.
- From isolated findings to connected claims and dependencies.
- From hiding disagreement to exposing contradiction and uncertainty.
- From static breadth-first decomposition alone to cyclic state-graph reasoning.

## Core Capabilities

The V2 system is expected to support all of the following:

1. Entity and relationship extraction from each document.
2. A persistent knowledge graph that accumulates cross-source triplets.
3. Contradiction detection with severity and evidence tracking.
4. Recursive research-gap discovery for missing jargon, assumptions, and
   foundational concepts.
5. Tie-breaker searches when high-severity claims conflict.
6. Final reports generated from graph structure, not raw snippets.
7. Eventual graph visualization for inspection and debugging.

## Architecture Direction

V2 uses a hybrid model.

- The Body: reuse and adapt V1 search, extraction, scraping, rate-limiting, and
  budget patterns.
- The Brain: implement a new sensemaking loop using a state graph, with agent
  nodes specialized for graph building, contradiction analysis, and synthesis.

Planned node sequence:

1. Scout
2. Analyst
3. Critic
4. Writer

Unlike V1, this is not a one-way pipeline. The router can send work back to
Scout when new gaps or disputes are discovered.

## Planned Repository Layout

The exact code layout may evolve, but the intended structure is:

```text
.
├── .github/
│   └── copilot-instructions.md
├── docs/
│   ├── prd.md
│   ├── architecture.md
│   ├── state-schema.md
│   ├── agents.md
│   ├── sensemaking-loop.md
│   ├── report-spec.md
│   ├── reuse-from-v1.md
│   └── implementation-plan.md
├── sensemaking-agent/
│   ├── prompts/
│   ├── src/
│   │   ├── main.py
│   │   ├── graph.py
│   │   ├── state.py
│   │   ├── nodes/
│   │   ├── tools/
│   │   ├── database/
│   │   └── visualisation/
│   └── tests/
├── CONTRIBUTING.md
├── USER_GUIDE.md
└── README.md
```

## Design Constraints

- Do not modify AI-Driven-Autonomous-Research-Agent as part of V2 work.
- Do not reduce V2 to a renamed copy of V1.
- Do not generate final reports from raw snippets alone.
- Do not treat contradiction as noise to average out.
- Do not start implementation from an ad hoc script without first aligning to the
  state schema and routing model in this docs set.

## Document Map

- Product requirements: [docs/prd.md](docs/prd.md)
- Architecture: [docs/architecture.md](docs/architecture.md)
- State contract: [docs/state-schema.md](docs/state-schema.md)
- Agent responsibilities: [docs/agents.md](docs/agents.md)
- Routing logic: [docs/sensemaking-loop.md](docs/sensemaking-loop.md)
- Report contract: [docs/report-spec.md](docs/report-spec.md)
- V1 reuse boundaries: [docs/reuse-from-v1.md](docs/reuse-from-v1.md)
- Implementation plan: [docs/implementation-plan.md](docs/implementation-plan.md)
- Contributor workflow: [CONTRIBUTING.md](CONTRIBUTING.md)
- Current onboarding guidance: [USER_GUIDE.md](USER_GUIDE.md)

## Relationship To V1

AI-Driven-Autonomous-Research-Agent remains the reference source for:

- Tavily integration patterns
- conditional scraping strategy
- budget awareness
- prompt organization
- resilient async I/O patterns

V2 deliberately diverges from V1 in its primary state model and output model.
The V1 topic graph is not the V2 knowledge graph.

## Near-Term Implementation Order

1. Lock the docs set in this repository.
2. Extract reusable Scout-layer tooling from V1 into a clean V2 tool boundary.
3. Implement the V2 state schema and graph export helpers.
4. Implement Analyst, Critic, and Writer nodes around structured outputs.
5. Implement the LangGraph orchestration and routing logic.
6. Add persistence, reporting, and graph visualization.

## Non-Goals For The First Build

- Reproducing every V1 CLI feature before the sensemaking loop exists.
- Building a broad UI before the core graph and report contracts stabilize.
- Adding multiple search providers before the Scout contract is proven with V1
  reuse.
- Premature optimization of graph storage before the in-memory model and
  persistence format are validated.