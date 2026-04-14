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

Phase: working end-to-end implementation with GraphRAG local-corpus integration

The repository has moved beyond planning and now contains a working Python
foundation for the state, routing, reporting, artifact layers, and GraphRAG-based
local corpus indexing and querying.

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
- latest result: `164 passed` (sensemaking-agent) + `78 passed` (graphragloader)

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
- `main.py`: CLI entry point (`--query`, `--topic-dir`, `--watch`, `--graphrag-dir`, `--max-iterations`, `--log-level`, `--output-dir`, `--no-persist`, `--dry-run`, `--tavily-key`, `--max-results`, `--max-queries`, `--max-credits`, `--warn-threshold`, `--no-scrape`, `--respect-robots`, `--no-respect-robots`)
- Analyst tests: parse_extraction, triplet_id, merge_entity helpers, full node integration (LLM stubbed)
- Critic tests (`tests/test_critic.py`): id helpers, parse helpers, iteration filtering, deduplication, contradiction detection, gap detection, missing prompt fallback (all LLM-stubbed, 28 new tests)
- Writer tests (`tests/test_writer.py`): bounded context preparation, output parsing, LLM-backed synthesis, malformed-output fallback, and empty-graph fallback
- persistence tests: artifact store output, automatic resume behavior, and workflow-integrated checkpoint/final artifact coverage
- visualization tests (`tests/test_visualisation.py`): GraphML, DOT, and HTML artifact export coverage, including local resource provenance in the viewer
- runtime wiring tests (`tests/test_main.py`): parser coverage, CLI-to-tool runtime configuration checks, `_parse_requirements_file` section and heading parsing, `_parse_topic_dir` convention discovery, mutually-exclusive `--query`/`--topic-dir` args, `build_initial_state` with pre-seeded documents, user_prompt, constraints, and watch-mode state
- resource loader tests (`tests/test_resource_loader.py`): text file loading, empty/nonexistent dirs, unsupported extensions, content truncation
- low-level LLM transport tests (`tests/test_llm_client.py`): Ollama path, OpenAI-compatible path, empty response handling, failure fallback, and async executor path
- `--topic-dir` CLI support: self-contained research folder convention with auto-discovered requirements.md, prompts/, resources/, output/; `.env` auto-loaded from topic dir
- `_parse_requirements_file()`: section-based parsing (`## Topic`, `## Research Focus`, `## Background`, `## Constraints`), heading fallback, backward compatibility
- `_parse_topic_dir()`: convention-based discovery of requirements.md/topic.md/first *.md, prompts/ and resources/ subdirs
- resource loader (`tools/resource_loader.py`): recursive directory scan of plain-text files (`.md`, `.txt`, `.rst`, `.csv`, `.tsv`, `.log`) into `SourceDocument` entries; no external dependencies required; complex formats (PDF, DOCX, EPUB, source code) must be pre-indexed via `graphragloader`
- `ResearchState.user_prompt`: background context field set from requirements.md, injected into all LLM node prompts via `$user_context` template variable
- `ResearchState.constraints`: optional guardrail field set from `## Constraints`, injected into Critic analysis and used to shape Scout query expansion
- watch-mode resource tracking: `watched_resources_dir` and `watched_resources_seen` fields let Scout ingest newly added files from `resources/` between iterations
- Scout query expansion: entities grounded in local resources are appended to later web queries so follow-up search is more resource-aware
- `build_initial_state()` extended with `documents`, `user_prompt`, `constraints`, and watch-mode kwargs for pre-seeding state with local resources
- `topicexample/` overhauled: real `.env` (gitignored), `resources/` folder, simplified `run.ps1`/`run.sh` using `--topic-dir`, section-reordered `requirements.md` (Topic → Research Focus → Background → Constraints)
- `.gitignore` updated with `.env` at root and `topicexample/.gitignore` for `.env` and `output/`
- Workflow tests: all patched for offline LLM where documents are processed
- **graphragloader companion package** (`graphragloader/`): standalone package for converting local files into a Microsoft GraphRAG index and querying it
  - `converter.py`: LlamaIndex-based file-to-text conversion (PDF, DOCX, EPUB, PPTX, images, notebooks) with stable filenames and metadata headers; PyMuPDF fallback for sparse-text PDFs; Tesseract OCR fallback for scanned PDFs with auto-detected or explicit language (`--ocr-lang`)
  - `code_analyzer.py`: Python ast + tree-sitter structural extraction for source code files
  - `settings.py`: GraphRAG settings.yaml and .env generation with Ollama and OpenAI provider support
  - `indexer.py`: async indexing wrapper with change detection (file hashes + state tracking) and CLI fallback
  - `query.py`: async local/global/drift/basic search dispatch against GraphRAG parquet output
  - `cli.py`: `graphragloader init|convert|index|query` entry points; `convert` supports `--ocr-lang` for explicit Tesseract language selection
- **GraphRAG integration in sensemaking-agent**:
  - `tools/graphrag_tool.py`: `GraphRAGTool` dataclass wrapping `graphragloader.query()` with `SourceDocumentState`-compatible output
  - `config.py`: `GraphRAGConfig` dataclass and `graphrag` field on `AgentConfig`
  - `nodes/scout_node.py`: `make_scout_node()` accepts optional `graphrag_tool`, queries GraphRAG before web search, merges results
  - `workflow.py`: `build_workflow()` passes `graphrag_tool` through to Scout node
  - `main.py`: `_parse_topic_dir()` auto-detects `graphrag/` with `settings.yaml`; `--graphrag-dir` CLI arg; `run()` creates `GraphRAGTool` when path is available
- graphragloader tests (78): converter, code_analyzer, settings, indexer, query, CLI
- sensemaking-agent GraphRAG tests: `test_graphrag_tool.py` (8 tests), `test_main.py` GraphRAG discovery tests (3 tests)
- `topicexample/` updated: `prepare.ps1`/`prepare.sh` for GraphRAG indexing, `graphrag/.gitignore`, updated README and resources docs

Not implemented yet:

- checked-in live-run verification guidance
- richer rendered graph outputs such as image export
- broader integration coverage against live Tavily and LLM backends

## Current Validation Status

Validated on 2026-04-06:

- sensemaking-agent: `164 passed in 1.81s`
- graphragloader: `78 passed in 1.18s`
- run from respective package directories

Known note:

- `python` on PATH still resolves to the Windows Store shim in this environment
- use the concrete interpreter path or `..\.\.venv\\Scripts\\python.exe` when validating
- on Windows, always specify `encoding="utf-8"` for text file reads (default is GBK)

## Next Recommended Steps

1. Add a checked-in live-run verification checklist for Tavily and LLM-backed runs
2. Expand graph rendering and inspection beyond the current GraphML, DOT, and HTML artifacts
3. Broaden integration coverage for real backend configurations and longer end-to-end runs
4. End-to-end live validation of graphragloader index + query pipeline with real LLM
5. Publish graphragloader to PyPI for standalone installation

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

### 2026-04-06

- created `graphragloader/` companion package for local corpus conversion and GraphRAG indexing
  - `converter.py`: LlamaIndex-based multi-format file conversion with stable filenames and metadata
  - `code_analyzer.py`: Python ast + tree-sitter code structural extraction
  - `settings.py`: GraphRAG settings.yaml generation (Ollama and OpenAI providers)
  - `indexer.py`: async indexing with file-hash change detection and CLI fallback
  - `query.py`: async local/global/drift/basic search dispatch
  - `cli.py`: `graphragloader init|convert|index|query` subcommands
  - `pyproject.toml`, `README.md`, `__init__.py` with full public API
- integrated GraphRAG into sensemaking-agent
  - `tools/graphrag_tool.py`: `GraphRAGTool` wrapping graphragloader query with SourceDocument output
  - `config.py`: added `GraphRAGConfig` dataclass and field on `AgentConfig`
  - `nodes/scout_node.py`: Scout queries GraphRAG before web search when tool available
  - `workflow.py`: passes `graphrag_tool` through to Scout node
  - `main.py`: `_parse_topic_dir()` auto-detects `graphrag/` directory; added `--graphrag-dir` CLI arg
- updated `topicexample/`: added `prepare.ps1`/`prepare.sh` indexing scripts, `graphrag/.gitignore`, updated README and resources docs
- created comprehensive test suites: 78 tests for graphragloader, 11 new tests for sensemaking-agent
- updated architecture.md, agents.md, reuse-from-v1.md, implementation-progress.md
- revalidated: sensemaking-agent `164 passed`, graphragloader `78 passed`

### 2026-04-06 (cleanup)

- stripped complex file format handling from `tools/resource_loader.py`: removed PDF/OCR, DOCX, EPUB, MOBI readers and their optional dependencies
- `resource_loader` now handles plain-text extensions only (`.md`, `.txt`, `.rst`, `.csv`, `.tsv`, `.log`); no external dependencies required
- removed `[resources]` optional dependency group from `sensemaking-agent/pyproject.toml` (pymupdf, python-docx, pytesseract, Pillow, EbookLib, beautifulsoup4, mobi)
- removed EPUB and MOBI dispatch tests from `test_resource_loader.py`; all 7 remaining tests pass
- updated `topicexample/resources/README.md`, `topicexample/README.md`, root `README.md`, `docs/implementation-progress.md`, and `docs/reuse-from-v1.md` to reflect plain-text-only boundary
- complex format conversion remains in `graphragloader` as the correct pre-processing step before GraphRAG indexing

### 2026-04-14

- **PDF OCR pipeline fix in `graphragloader/converter.py`** — Chinese scanned-image PDFs (e.g. finance books) were converting to only a few hundred characters because the small promo page at the front prevented the empty-text OCR gate from firing
  - added `_HAS_PYMUPDF` flag and optional PyMuPDF import (`fitz`)
  - added `_read_pdf_with_pymupdf(path)` — page-by-page PyMuPDF extraction
  - added `_pdf_text_is_sparse(text, file_size_bytes)` — heuristic: `meaningful_chars < max(500, file_size/50KB × 500)` catches scanned PDFs that have minimal embedded text
  - rewrote LlamaIndex PDF processing loop: sparse → try PyMuPDF → still sparse → try OCR
  - added `_detect_ocr_lang()` — queries tesseract installed languages, returns `chi_sim+eng` when available
  - added `lang` parameter to `_read_ocr_image()` and `_read_pdf_with_ocr()`
  - added `ocr_lang: Optional[str] = None` to `convert_resources()`, `_convert_files()`, `_extract_zip()`, and `_extract_rar()` signatures; threaded through all recursive call sites
  - added `--ocr-lang` CLI flag to `graphragloader convert` subcommand
  - added `pymupdf` optional dependency group to `graphragloader/pyproject.toml`
- **OCR dependencies installed**: `pymupdf 1.27.2.2`, `pdf2image`, Poppler (via WinGet), Tesseract OCR with `chi_sim` tessdata downloaded to `$env:USERPROFILE\tessdata`
- **Finance workflow scripts updated** (`run_finance_analysis.ps1`, `run_finance_analysis_cloud.ps1`)
  - set `$env:TESSDATA_PREFIX = "$env:USERPROFILE\tessdata"` at startup so Tesseract finds the user-scoped tessdata folder
  - pass `--ocr-lang chi_sim+eng` to the convert step automatically — no manual CLI invocation needed
  - auto-resume by default: convert skipped when `.convert_done.json` exists; index skipped when `.shard_status.json` has `#completed=true`
  - elapsed-time tracking in `.shard_status.json` (`#elapsed_min`) for speed comparison
- **`run_finance_analysis_cloud.ps1` created** — runs the same corpus with `gemma4:31b-cloud` (Ollama-hosted cloud model) into `D:\FinanceRAG-cloud`
  - `Confirm-OllamaModelsInstalled` skips `/api/tags` check for models with `-cloud` suffix (not downloaded locally)
  - `Wait-OllamaModel` uses a quick test generate instead of `/api/ps` polling for cloud models
  - auto-detects manually copied `input/` files and writes `.convert_done.json` marker to skip re-convert
  - `Show-ResumptionGuide` prints side-by-side speed comparison when both local and cloud `.shard_status.json` files exist