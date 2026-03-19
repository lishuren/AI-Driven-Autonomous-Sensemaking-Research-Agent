# Implementation Progress

## Purpose

This document is the durable day-to-day implementation log for the repository.

Use it to track:

- what is already implemented
- what was validated
- what is blocked
- what should happen next

Unlike the architecture and specification docs, this file is expected to change
frequently as the codebase moves forward.

## Current Status

Phase: early implementation

The repository has moved beyond planning and now contains a working Python
foundation for the state and routing layers.

## Completed

### Documentation foundation

- root README, user guide, contributing guide, and Copilot instructions created
- PRD, architecture, state schema, agent contracts, routing spec, report spec,
  and V1 reuse boundary docs created
- before-and-after documentation review rule added to repo guidance

### Package scaffolding

- Python package scaffold created under `sensemaking-agent/`
- `pyproject.toml` added
- package README and prompt README added
- package namespace and module layout added

### State and graph core

- canonical state records implemented in `sensemaking_agent.state`
- merge, validation, and metrics helpers implemented
- NetworkX directed graph export implemented

### Routing core

- route names, route decisions, and router config implemented in
  `sensemaking_agent.graph`
- conflict resolution, gap resolution, saturation, and finalize decisions
  implemented
- route application back into state implemented

### Validation

- project dependencies installed with Python 3.12.7
- current automated test suite passes
- latest result: `43 passed`

## Current Code Surface

Implemented now:

- package metadata and editable install configuration
- state models and helpers
- graph export helper
- route-decision logic
- state and routing tests
- Scout acquisition tooling (`ScoutTool`, `SearchTool`, `ScraperTool`)
- config module for Tavily, scraper, budget, and LLM settings (`AgentConfig`, `LLMConfig`)
- Scout tests (dry-run, budget guard, missing API key, all acquisition tiers, document normalization)
- budget `approaching_limit` correctly treats `warn_threshold=1.0` as disabled
- LangGraph workflow wired: Scout → Analyst → Critic → Router → Writer
- Scout node: bridges ScoutTool into state
- **Analyst node** (`nodes/analyst_node.py`): full LLM-backed extraction — entities, triplets, evidence, alias merging; skips already-processed documents; JSON output parsed via Pydantic; prompt driven by `prompts/analyst_extract.md`
- **Critic node** (`nodes/critic_node.py`): full LLM-backed contradiction and gap detection — compares triplets from current iteration against existing graph; records `ContradictionState` and `ResearchGapState` with hash-based IDs; deduplicates against already-stored records; never overwrites prior evidence; prompt driven by `prompts/critic_analyze.md`
- Router node: wraps `should_continue` and returns `Command` for dynamic routing
- Writer node stub: stores placeholder synthesis with counts
- `llm_client.py`: thin async Ollama / OpenAI-compatible LLM wrapper (executor-offloaded)
- `prompt_loader.py`: loads prompt files from bundled `prompts/` directory or custom path
- `prompts/analyst_extract.md`: entity and triplet extraction prompt (directional predicates, evidence requirement, confidence scoring)
- `prompts/critic_analyze.md`: contradiction and gap detection prompt (both-sides evidence preservation, severity and priority scoring rules, strict JSON output schema)
- `workflow.py`: builds and compiles the `StateGraph`; accepts `llm_config`
- `main.py`: CLI entry point (`--query`, `--max-iterations`, `--log-level`)
- Analyst tests: parse_extraction, triplet_id, merge_entity helpers, full node integration (LLM stubbed)
- Critic tests (`tests/test_critic.py`): id helpers, parse helpers, iteration filtering, deduplication, contradiction detection, gap detection, missing prompt fallback (all LLM-stubbed, 28 new tests)
- Workflow tests: all patched for offline LLM where documents are processed

Not implemented yet:

- Writer synthesis from knowledge graph (graph-grounded narrative)
- persistence (JSON checkpoint after each iteration)
- visualization

## Current Validation Status

Validated on 2026-03-20:

- `.venv\Scripts\python.exe -m pytest tests/ -q`
- result: `102 passed in 0.87s`
- run from `sensemaking-agent/` directory

Known note:

- `python` on PATH still resolves to the Windows Store shim in this environment
- use the concrete interpreter path or `.venv\Scripts\python.exe` when validating

## Next Recommended Steps

1. Implement Writer synthesis from the knowledge graph (graph-grounded narrative, contradiction log, evidence trails)
2. Add persistence (JSON checkpoint after each iteration)
3. Add visualization (graph export to DOT or rendering)

## Blockers

No active code blockers.

Operational caution:

- use the concrete Python interpreter path for validation commands until PATH is
  cleaned up

## Update Protocol

When work continues on a later day:

1. read this file first
2. update `Completed`, `Current Validation Status`, `Next Recommended Steps`,
   and `Blockers` as part of the same work item
3. if implementation changes the product contract, update the relevant spec docs
   as well
4. do not treat this file as a substitute for architecture or state-schema docs

## Session Log

### 2026-03-19

- created the docs-first foundation for the repo
- created the Python package scaffold
- implemented the state and graph helper layer
- implemented the initial router layer
- fixed a router metrics bug affecting graph saturation behavior
- installed dependencies and validated the current tests successfully