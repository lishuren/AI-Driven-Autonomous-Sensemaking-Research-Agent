# AI-Driven Autonomous Sensemaking Research Agent

An autonomous research system focused on sensemaking rather than summary generation.

This repository is the V2 direction for the research workflow pioneered in
AI-Driven-Autonomous-Research-Agent. It reuses proven search and scraping ideas
from V1, but the core product here is different: the primary output is a
graph-grounded explanation of how entities, claims, and uncertainties relate,
not a linear list of findings.

## Status

The core sensemaking pipeline is implemented and runnable end-to-end.

- Full LangGraph workflow: Scout → Analyst → Critic → Router → Writer.
- Entity and relationship extraction with structured Pydantic output contracts.
- Contradiction detection with severity, evidence, and tie-breaker routing.
- Research-gap discovery with recursive loop-back to Scout.
- Graph-grounded Writer synthesis with deterministic fallback.
- Per-run artifact persistence — checkpoints, final report, graph export, HTML viewer.
- Automatic resume of the latest unfinished run for the same query.
- CLI acquisition controls: dry-run, budget limits, Tavily key override, scraper policy.
- Visualization exports for GraphML, DOT, and a lightweight HTML viewer.
- 123 automated tests across state, tools, nodes, workflow, persistence, and LLM transport.

## Quick Start

### Prerequisites

- Python 3.10+
- Either a local [Ollama](https://ollama.ai/) server with a model pulled, or an
  OpenAI-compatible endpoint such as [SiliconFlow](https://www.siliconflow.cn)
- A **Tavily API key** — set `TAVILY_API_KEY` in your environment or pass
  `--tavily-key`. Sign up at [tavily.com](https://tavily.com) (free tier:
  1,000 credits/month).

### Install

```bash
cd sensemaking-agent
pip install -e ".[dev]"
python -m playwright install chromium
```

### Configure

Create `sensemaking-agent/.env` with your API keys (see `topicexample/.env` for
an example).  At minimum set `TAVILY_API_KEY`.

LLM defaults to Ollama at `http://localhost:11434` with model `qwen2.5:7b`.
Override via environment variables (see `.env.example` for all options).

### Run

```bash
# From sensemaking-agent/

# Basic run (Ollama + qwen2.5:7b must be running)
python -m sensemaking_agent --query "lithium supply chain risks"

# Use a self-contained topic directory (recommended)
python -m sensemaking_agent --topic-dir ../topicexample

# Limit iterations and choose an output directory
python -m sensemaking_agent --query "CRISPR gene editing mechanisms" \
  --max-iterations 3 \
  --output-dir ./data/runs

# Dry run — no Tavily calls, useful for offline development
python -m sensemaking_agent --query "quantum computing" --dry-run

# Use SiliconFlow instead of Ollama
SENSEMAKING_LLM_PROVIDER=openai \
SENSEMAKING_LLM_BASE_URL=https://api.siliconflow.cn/v1 \
SENSEMAKING_LLM_API_KEY=sk-YOUR-KEY \
SENSEMAKING_LLM_MODEL=Qwen/Qwen2.5-7B-Instruct \
python -m sensemaking_agent --query "lithium supply chain risks"

# With budget controls
python -m sensemaking_agent --query "AI safety" \
  --max-queries 20 \
  --max-credits 50.0 \
  --warn-threshold 0.8

# Disable Playwright fallback scraping
python -m sensemaking_agent --query "climate tipping points" --no-scrape

# Resume an interrupted run automatically (re-run the same command)
python -m sensemaking_agent --query "lithium supply chain risks" \
  --output-dir ./data/runs
```

To check your Tavily credit balance at any time:

```bash
python sensemaking-agent/check_tavily_usage.py
```

### CLI Reference

| Flag | Default | Description |
|------|---------|-------------|
| `--query QUERY` | — | Research question or topic (mutually exclusive with `--topic-dir`) |
| `--topic-dir DIR` | — | Self-contained topic folder with requirements.md, prompts/, resources/ |
| `--max-iterations N` | `5` | Maximum sensemaking loop iterations |
| `--output-dir DIR` | `data/runs` | Directory for checkpoints and final artifacts |
| `--no-persist` | off | Disable writing artifacts to disk |
| `--prompt-dir DIR` | bundled | Directory with custom prompt template overrides |
| `--dry-run` | off | Disable live Tavily calls (offline orchestration) |
| `--tavily-key KEY` | env | Tavily API key override for this run |
| `--max-results N` | `5` | Maximum Tavily results per search call |
| `--max-queries N` | unlimited | Maximum Tavily API calls for this run |
| `--max-credits CREDITS` | unlimited | Maximum Tavily credits to spend |
| `--warn-threshold FRACTION` | `0.80` | Warn when budget hits this fraction of a limit |
| `--no-scrape` | off | Disable Playwright fallback scraper |
| `--respect-robots` / `--no-respect-robots` | env (`true`) | robots.txt advisory check |
| `--log-level LEVEL` | `INFO` | Logging verbosity |

### Environment Variables

LLM settings are configured via environment variables (no CLI flags):

| Variable | Default | Description |
|----------|---------|-------------|
| `TAVILY_API_KEY` | — | Tavily API key (required for live runs) |
| `SENSEMAKING_LLM_MODEL` | `qwen2.5:7b` | LLM model name |
| `SENSEMAKING_LLM_PROVIDER` | `ollama` | Provider: `ollama` or `openai` |
| `SENSEMAKING_LLM_BASE_URL` | `http://localhost:11434` | LLM server base URL |
| `SENSEMAKING_LLM_API_KEY` | — | API key for online providers |
| `SENSEMAKING_MAX_QUERIES` | unlimited | Max Tavily calls per run |
| `SENSEMAKING_MAX_CREDITS` | unlimited | Max Tavily credits per run |
| `SENSEMAKING_NO_SCRAPE` | `false` | Disable Playwright scraping |
| `SENSEMAKING_RESPECT_ROBOTS` | `true` | Advisory robots.txt check |
| `SENSEMAKING_PROMPT_DIR` | — | Custom prompt template directory |

CLI flags always take precedence over environment variables.

### Topic Directory Convention

Instead of passing `--query` with many flags, create a self-contained folder:

```text
my-topic/
├── .env              ← API keys and budget (auto-loaded, gitignored)
├── requirements.md   ← topic spec (## Topic, ## Research Focus, ## Background)
├── prompts/          ← optional prompt template overrides
├── resources/        ← optional local PDFs, Word docs, Markdown, text
└── output/           ← auto-created; run artifacts go here
```

Run with:

```bash
python -m sensemaking_agent --topic-dir ./my-topic
```

No `--query`, `--output-dir`, or `--prompt-dir` needed — all paths are derived
from the folder layout.  Local documents in `resources/` are loaded as seed
documents into the knowledge graph before the first web search.

See `topicexample/` for a complete working example.

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
7. Graph visualization for inspection and debugging.

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
│   ├── .env                  ← API keys — gitignored, copy from topicexample/.env
│   ├── check_tavily_usage.py ← check Tavily credit balance
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
- Implementation progress: [docs/implementation-progress.md](docs/implementation-progress.md)
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

## Near-Term Improvements

1. Checked-in live-run verification checklist.
2. Expand graph inspection and rendering beyond the current artifact set.
3. Harden report quality against longer real-world runs.
4. Broaden integration coverage against live LLM and Tavily configurations.

## Current Implementation Snapshot

The repository contains a working end-to-end sensemaking pipeline:

- Python package scaffold in `sensemaking-agent/`
- Pydantic-backed state models and merge helpers
- NetworkX knowledge graph with export support
- Scout acquisition tooling adapted from V1 search and scraping patterns
- LangGraph workflow wiring: Scout → Analyst → Critic → Router → Writer
- LLM-backed Analyst and Critic nodes with structured JSON parsing
- Graph-grounded Writer synthesis with deterministic fallback behavior
- Runnable CLI entry point for iterative sensemaking runs
- Per-run artifact persistence: initial state, checkpoints, final state,
  final report, graph export, and visualization artifacts
- Automatic resume of the latest unfinished run for the same query
- CLI acquisition controls: dry-run mode, budget limits, Tavily key override,
  scraper policy switches
- Router decision logic for conflict resolution, gap resolution, continuation,
  and finalization
- Visualization exports for GraphML, DOT, and HTML inspection
- 123 automated tests across state, tools, nodes, workflow, persistence,
  visualization, runtime configuration, and LLM transport behavior

Gaps that do not block production use:

- No checked-in live-run verification checklist yet.
- No image-format (PNG) graph export yet.
- No live-backend integration tests in the test suite.

## Non-Goals For The First Build

- Reproducing every V1 CLI feature before the sensemaking loop exists.
- Building a broad UI before the core graph and report contracts stabilize.
- Adding multiple search providers before the Scout contract is proven with V1
  reuse.
- Premature optimization of graph storage before the in-memory model and
  persistence format are validated.