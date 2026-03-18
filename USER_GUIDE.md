# User Guide

This repository is in a documentation-first implementation phase.

The goal of this guide is not yet to walk through a finished runtime. Instead,
it explains how contributors should use the documentation package in this repo
to start implementation without drifting away from the intended architecture.

## Current State

At the moment, this repository should be treated as:

- a product definition for the Sensemaking agent
- an architecture contract for future contributors
- a guardrail set for Copilot-assisted development

It should not yet be treated as a runnable replacement for V1.

## What To Read First

Use this order:

1. [README.md](README.md)
2. [.github/copilot-instructions.md](.github/copilot-instructions.md)
3. [docs/prd.md](docs/prd.md)
4. [docs/architecture.md](docs/architecture.md)
5. [docs/state-schema.md](docs/state-schema.md)
6. [docs/sensemaking-loop.md](docs/sensemaking-loop.md)
7. [docs/report-spec.md](docs/report-spec.md)
8. [docs/reuse-from-v1.md](docs/reuse-from-v1.md)

That sequence moves from product intent to implementation constraints.

## How To Use V1 Correctly

AI-Driven-Autonomous-Research-Agent is reference-only.

Use it to understand:

- Tavily search patterns
- conditional scraping behavior
- prompt organization
- async orchestration patterns
- budget controls and failure handling

Do not:

- edit V1 files while implementing V2
- copy V1 architecture wholesale
- assume V1 TopicGraph is the V2 memory model
- assume V1 markdown report structure is enough for graph-grounded synthesis

## Contributor Workflow

Every implementation task in this repository should follow this order:

1. Check the architecture and state docs before writing code.
2. Confirm the task fits the Scout, Analyst, Critic, Writer, or routing layer.
3. Reuse V1 only at the tool or utility level unless a doc explicitly says
   otherwise.
4. Prefer structured output contracts before writing free-form prompts.
5. Keep the knowledge graph and contradiction log as first-class outputs.
6. Update docs if implementation reveals a mismatch in the contract.

## Planned Initial Build Sequence

The intended first implementation wave is:

1. Create the Python package skeleton under `sensemaking-agent/`.
2. Implement the Scout boundary by adapting V1 search and scraping logic.
3. Implement the V2 `ResearchState` and graph helper utilities.
4. Implement structured Analyst extraction.
5. Implement Critic contradiction and gap detection.
6. Implement router logic and stop conditions.
7. Implement Writer synthesis from graph data.
8. Add persistence and graph visualization.

## Environment Assumptions

The intended stack for V2 is:

- Python 3.10+
- LangGraph for orchestration
- Pydantic for structured LLM outputs
- NetworkX for in-memory graph operations
- Tavily for search and extract
- Playwright as the browser fallback
- Ollama or another compatible LLM endpoint for local or remote inference

These are design assumptions for the first implementation pass, not a fully
provisioned runtime yet.

## Definition Of Done For The Docs-First Phase

The docs-first phase is complete when:

1. the state model is explicit and serializable
2. the routing logic is unambiguous
3. the report contract is graph-grounded
4. the V1 reuse boundary is explicit
5. the Copilot instructions are strong enough to keep generated code aligned

## What To Do Next

If you are starting implementation after reading this guide:

1. follow [docs/implementation-plan.md](docs/implementation-plan.md)
2. treat [.github/copilot-instructions.md](.github/copilot-instructions.md) as
   the coding guardrail
3. keep V1 open in the workspace only as a reference source