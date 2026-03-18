# Contributing

## Working Agreement

This repository is building a new product that selectively reuses components from
AI-Driven-Autonomous-Research-Agent.

The default rule is:

- reuse proven V1 tool patterns where they help
- do not collapse V2 back into V1 architecture

## Before You Write Code

Read these files first:

1. [.github/copilot-instructions.md](.github/copilot-instructions.md)
2. [docs/architecture.md](docs/architecture.md)
3. [docs/state-schema.md](docs/state-schema.md)
4. [docs/sensemaking-loop.md](docs/sensemaking-loop.md)
5. [docs/reuse-from-v1.md](docs/reuse-from-v1.md)

If the code you want to write conflicts with those documents, update the docs or
raise the mismatch before continuing.

Before starting a code change, contributors must review the relevant documents
for that area and confirm the intended contract is still correct.

## Scope Boundaries

Contributors must not:

- modify AI-Driven-Autonomous-Research-Agent as part of V2 work
- implement a summary-first report path as the main output model
- bypass the contradiction log or research-gap loop
- add direct dependencies between the Scout tooling and the orchestration state

## Implementation Priorities

Build in this order:

1. Scout tool boundary
2. ResearchState and graph helpers
3. Analyst node
4. Critic node
5. Router and LangGraph wiring
6. Writer node
7. Persistence and report generation
8. Visualization and observability

## Coding Standards

- Use Python with explicit type hints.
- Keep public I/O async.
- Use Pydantic models or equivalent structured contracts for LLM outputs.
- Keep state serializable at orchestration boundaries.
- Prefer composition over monolithic modules.
- Keep prompts versioned as files, not hard-coded multiline strings, unless a
  short inline prompt is necessary for a test.

## Testing Expectations

When implementation begins, each layer should have focused tests:

1. state-schema and graph helper tests
2. Scout normalization and fallback tests
3. Analyst output parsing and merge behavior tests
4. Critic contradiction and gap detection tests
5. router decision tests
6. report formatting tests

Until the code exists, these expectations act as the design target.

## Documentation Discipline

This repository is docs-led.

Every code change should have a documentation pass both before and after the
implementation work:

1. Before code changes: review the relevant docs and either align the planned
  implementation to them or update the docs first if the contract has changed.
2. After code changes: review the affected docs again and update any stale
  status, behavior, API, workflow, or sequencing details in the same work item.

When you change one of these contracts, update the matching documentation in the
same work item:

- state fields
- node responsibilities
- route names and stop conditions
- final report sections
- V1 reuse boundary

This applies both to architecture/spec docs and to implementation-status docs
such as the root README, user guide, and package README when they describe the
current state of the codebase.

## Copilot Usage

Copilot should be guided by [.github/copilot-instructions.md](.github/copilot-instructions.md).
If generated code drifts toward a simple linear RAG implementation, correct it
immediately rather than accepting incremental drift.