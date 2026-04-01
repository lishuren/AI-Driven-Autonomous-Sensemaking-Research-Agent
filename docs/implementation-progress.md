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

Phase: working end-to-end implementation with persistence, resume, and inspection artifacts

The repository has moved beyond planning and now contains a working Python
foundation for the state, routing, reporting, and artifact layers.

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

- project dependencies installed with Python 3.12.9
- current automated test suite passes
- latest result: `123 passed`

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
- **Writer node** (`nodes/writer_node.py`): graph-grounded Markdown synthesis from entities, triplets, contradictions, research gaps, and metrics; prompt driven by `prompts/writer_synthesize.md`; validates structured LLM output and falls back to a deterministic report when LLM output is missing or malformed
- deterministic Writer context builder (`sensemaking_agent.synthesis.prepare_writer_context`): ranks salient entities and triplets, groups candidate pillars, and prepares bounded graph context without concatenating raw document text
- run artifact persistence: per-run artifact directories with `initial_state.json`, `checkpoint.iter-###.json`, `final_state.json`, `report.md`, `graph.json`, and `run_manifest.json`
- automatic resume: rerunning the same query in the same output directory reuses the latest unfinished run and records resume metadata in the manifest
- visualization artifacts: `graph.graphml`, `graph.dot`, and a self-contained `graph.html` viewer are written with final run outputs
- `llm_client.py`: thin async Ollama / OpenAI-compatible LLM wrapper (executor-offloaded)
- `prompt_loader.py`: loads prompt files from bundled `prompts/` directory or custom path
- `prompts/analyst_extract.md`: entity and triplet extraction prompt (directional predicates, evidence requirement, confidence scoring)
- `prompts/critic_analyze.md`: contradiction and gap detection prompt (both-sides evidence preservation, severity and priority scoring rules, strict JSON output schema)
- `prompts/writer_synthesize.md`: graph-grounded report synthesis prompt with strict JSON output requirements
- `workflow.py`: builds and compiles the `StateGraph`; accepts `llm_config`
- `main.py`: CLI entry point (`--query`, `--max-iterations`, `--log-level`, `--output-dir`, `--no-persist`, `--dry-run`, `--tavily-key`, `--max-results`, `--max-queries`, `--max-credits`, `--warn-threshold`, `--no-scrape`, `--respect-robots`, `--no-respect-robots`)
- Analyst tests: parse_extraction, triplet_id, merge_entity helpers, full node integration (LLM stubbed)
- Critic tests (`tests/test_critic.py`): id helpers, parse helpers, iteration filtering, deduplication, contradiction detection, gap detection, missing prompt fallback (all LLM-stubbed, 28 new tests)
- Writer tests (`tests/test_writer.py`): bounded context preparation, output parsing, LLM-backed synthesis, malformed-output fallback, and empty-graph fallback
- persistence tests: artifact store output, automatic resume behavior, and workflow-integrated checkpoint/final artifact coverage
- visualization tests (`tests/test_visualisation.py`): GraphML, DOT, and HTML artifact export coverage
- runtime wiring tests (`tests/test_main.py`): parser coverage, CLI-to-tool runtime configuration checks, `_parse_requirements_file` section and heading parsing, `_parse_topic_dir` convention discovery, mutually-exclusive `--query`/`--topic-dir` args, `build_initial_state` with pre-seeded documents and user_prompt
- resource loader tests (`tests/test_resource_loader.py`): text file loading, empty/nonexistent dirs, unsupported extensions, content truncation
- low-level LLM transport tests (`tests/test_llm_client.py`): Ollama path, OpenAI-compatible path, empty response handling, failure fallback, and async executor path
- `--topic-dir` CLI support: self-contained research folder convention with auto-discovered requirements.md, prompts/, resources/, output/; `.env` auto-loaded from topic dir
- `_parse_requirements_file()`: section-based parsing (`## Topic`, `## Research Focus`, `## Background`), heading fallback, backward compatibility
- `_parse_topic_dir()`: convention-based discovery of requirements.md/topic.md/first *.md, prompts/ and resources/ subdirs
- resource loader (`tools/resource_loader.py`): flat directory scan of local PDF, DOCX, Markdown, and text files into `SourceDocument` entries; pymupdf + pytesseract OCR for scanned PDFs; python-docx for Word files; all optional deps with graceful degradation
- `ResearchState.user_prompt`: background context field set from requirements.md, injected into all LLM node prompts via `$user_context` template variable
- `build_initial_state()` extended with `documents` and `user_prompt` kwargs for pre-seeding state with local resources
- `topicexample/` overhauled: real `.env` (gitignored), `resources/` folder, simplified `run.ps1`/`run.sh` using `--topic-dir`, section-reordered `requirements.md` (Topic → Research Focus → Background)
- `.gitignore` updated with `.env` at root and `topicexample/.gitignore` for `.env` and `output/`
- Workflow tests: all patched for offline LLM where documents are processed

Not implemented yet:

- checked-in live-run verification guidance
- richer rendered graph outputs such as image export
- broader integration coverage against live Tavily and LLM backends

## Current Validation Status

Validated on 2026-04-02:

- `..\.venv\Scripts\python.exe -m pytest tests -q`
- result: `143 passed in 1.17s`
- run from `sensemaking-agent/` directory

Known note:

- `python` on PATH still resolves to the Windows Store shim in this environment
- use the concrete interpreter path or `..\.venv\Scripts\python.exe` when validating

## Next Recommended Steps

1. Add a checked-in live-run verification checklist for Tavily and LLM-backed runs
2. Expand graph rendering and inspection beyond the current GraphML, DOT, and HTML artifacts
3. Broaden integration coverage for real backend configurations and longer end-to-end runs

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

### 2026-04-01

- added per-run artifact persistence for initial state, iteration checkpoints,
  final state, Markdown report, and graph export
- wired persistence into the router and writer lifecycle points
- updated the CLI with `--output-dir` and `--no-persist`
- revalidated the full `sensemaking-agent` test suite successfully
- replaced the Writer stub with prompt-driven graph-grounded synthesis plus deterministic fallback report generation
- added `writer_synthesize.md`, bounded Writer context preparation, and Writer-focused tests
- changed rerun behavior to automatically resume the latest unfinished run for the same query and output directory
- added visualization exports for GraphML, DOT, and a lightweight HTML graph viewer
- added CLI acquisition controls for dry-run mode, Tavily key override, budget limits, and scraper policy switches
- added low-level `llm_client.py` tests
- revalidated the full suite at `123 passed`

### 2026-04-02

- removed the GitHub Actions CI workflow (`.github/workflows/sensemaking-tests.yml`)
- fixed deprecated `asyncio.get_event_loop()` to `asyncio.get_running_loop()` in `llm_client.py`
- fixed stale docstrings in `nodes/writer_node.py`, `__init__.py`, and `pyproject.toml`
- added `reset_runtime_state` re-exports to `tools/__init__.py`
- refreshed `README.md`, `USER_GUIDE.md`, `sensemaking-agent/README.md`, and `docs/implementation-progress.md` to remove CI references
- revalidated the full suite at `123 passed`

### 2026-04-03

- added `--topic-dir` CLI support with convention-based path resolution
- added `_parse_requirements_file()` and `_parse_topic_dir()` in `main.py`
- created `tools/resource_loader.py` with PDF (pymupdf + OCR), DOCX, and text file reading
- added `user_prompt` field to `ResearchState` and extended `build_initial_state()` with pre-seeded documents
- injected `$user_context` template variable into all 3 LLM node prompts (analyst, critic, writer)
- overhauled `topicexample/`: real `.env`, `resources/` folder, simplified run scripts, section-reordered requirements.md
- added `.env` to root `.gitignore`, created `topicexample/.gitignore`
- created `sensemaking-agent/.env` with real API keys
- updated `README.md` and `USER_GUIDE.md` with `--topic-dir` documentation
- added 20 new tests: `_parse_requirements_file`, `_parse_topic_dir`, arg parser, resource loader, `build_initial_state` extensions
- revalidated the full suite at `143 passed`