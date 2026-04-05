# User Guide: Checkout to First Query

This guide walks you from a fresh checkout to running your first sensemaking
research query with either a local Ollama model or an online OpenAI-compatible
provider such as SiliconFlow.

## 1. Checkout the code

```bash
git clone <your-repo-url>
cd AI-Driven-Autonomous-Sensemaking-Research-Agent/sensemaking-agent
```

If you already have the repository, just `cd` into `sensemaking-agent/`.

## 2. Set up Python and project dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
python -m playwright install chromium

# Optional: install graphragloader for local corpus indexing
cd ../graphragloader
pip install -e ".[all]"
cd ../sensemaking-agent
```

Notes:
- Python 3.10+ is required.
- On some Linux distributions, Playwright may also need OS packages. If the
  Chromium install fails, run:

```bash
python -m playwright install --with-deps chromium
```

## 3. Choose an LLM provider

You can run the agent with either:

- **Ollama** — local models on your machine
- **SiliconFlow / OpenAI-compatible API** — hosted models

### Option A: Install Ollama (Linux / macOS)

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Verify installation:

```bash
ollama --version
```

## 4. Start Ollama

Run Ollama in a separate terminal:

```bash
ollama serve
```

Keep it running while you use the agent.

## 5. Download a model

Pull at least one model. Example:

```bash
ollama pull qwen2.5:7b
```

Optional sanity check against Ollama directly:

```bash
ollama run qwen2.5:7b "In one sentence, explain the lithium supply chain."
```

### Option B: Use SiliconFlow instead of Ollama

If you prefer an online model, set the LLM environment variables in `.env`
(see step 6) or export them in your shell:

```bash
export SENSEMAKING_LLM_PROVIDER=openai
export SENSEMAKING_LLM_BASE_URL=https://api.siliconflow.cn/v1
export SENSEMAKING_LLM_API_KEY=sk-YOUR-SILICONFLOW-KEY
export SENSEMAKING_LLM_MODEL=Qwen/Qwen2.5-7B-Instruct
```

## 6. Set up your Tavily API key

The agent uses **Tavily** for web search. Get a free API key at
[app.tavily.com](https://app.tavily.com) (free tier: 1,000 credits/month).

### Option A: `.env` file (recommended)

Create `sensemaking-agent/.env` with your keys (see `topicexample/.env` for a
working example):

```bash
# sensemaking-agent/.env
TAVILY_API_KEY=tvly-YOUR-API-KEY-HERE
```

The agent loads `sensemaking-agent/.env` automatically — no `export` needed.

### Option B: Shell export

```bash
export TAVILY_API_KEY="tvly-YOUR-API-KEY-HERE"
```

### Option C: Inline CLI flag

```bash
python -m sensemaking_agent --query "..." --tavily-key tvly-YOUR-API-KEY-HERE
```

### Checking your credit balance

After setting up the key you can verify it and see how many credits remain:

```bash
python check_tavily_usage.py
```

Example output:

```
API key  : tvly-dev...XXXX
Checking usage...

──────────────────────────────────────────────────
  Tavily Credit Usage  (source: /usage endpoint)
──────────────────────────────────────────────────
  Plan      : Researcher
  This Key  :        42  ← matches app.tavily.com API Keys tab
  Plan Used :        42  (all keys combined)
  Plan Limit:     1,000
  Remaining:        958
  Progress (plan): [████░░░░░░░░░░░░░░░░░░░░░░░░░░]  4.2%
──────────────────────────────────────────────────
```

Each run appends a snapshot to `data/tavily_usage_history.jsonl`.

## 7. Run your first sensemaking query

### Option A: Topic directory (recommended)

The simplest approach is to use a self-contained topic folder.  The included
`topicexample/` shows the convention:

```bash
cd sensemaking-agent

# Optional: build a GraphRAG index from local resources first
cd ../topicexample && graphragloader index --source resources --target graphrag && cd ../sensemaking-agent

python -m sensemaking_agent --topic-dir ../topicexample
```

The agent auto-discovers `requirements.md`, loads `.env`, applies `prompts/`
overrides, reads local `resources/`, detects `graphrag/` for corpus querying,
and writes output to `output/` — all inside the topic folder.  `requirements.md` may include `## Constraints` to
keep follow-up research bounded, and `--watch` can be added to ingest newly
added resource files on later iterations without restarting the run.

### Option B: Inline query

From `sensemaking-agent/`:

```bash
python -m sensemaking_agent --query "lithium supply chain risks"
```

With iteration and output controls:

```bash
python -m sensemaking_agent \
  --query "CRISPR gene editing mechanisms" \
  --max-iterations 3 \
  --output-dir ./data/runs \
  --log-level INFO
```

Or against SiliconFlow:

```bash
SENSEMAKING_LLM_PROVIDER=openai \
SENSEMAKING_LLM_BASE_URL=https://api.siliconflow.cn/v1 \
SENSEMAKING_LLM_API_KEY=sk-YOUR-KEY \
SENSEMAKING_LLM_MODEL=Qwen/Qwen2.5-7B-Instruct \
python -m sensemaking_agent --query "lithium supply chain risks" --max-iterations 3
```

## 8. CLI reference

| Flag | Default | Description |
|------|---------|-------------|
| `--query QUERY` | — | Research question or topic (mutually exclusive with `--topic-dir`) |
| `--topic-dir DIR` | — | Self-contained topic folder with requirements.md, prompts/, resources/ |
| `--graphrag-dir DIR` | auto | Path to a pre-built GraphRAG index directory (auto-detected in topic dirs) |
| `--watch` | off | Poll `resources/` during the run and ingest newly added local files |
| `--max-iterations N` | `5` | Maximum sensemaking loop iterations |
| `--output-dir DIR` | `data/runs` | Directory for checkpoints and final artifacts |
| `--no-persist` | off | Disable writing artifacts to disk |
| `--prompt-dir DIR` | bundled | Directory with custom prompt template overrides |
| `--dry-run` | off | Disable live Tavily calls (offline orchestration) |
| `--tavily-key KEY` | env | Tavily API key override for this run |
| `--max-results N` | `5` | Maximum Tavily results per search call |
| `--max-queries N` | unlimited | Maximum Tavily API calls for this run |
| `--max-credits CREDITS` | unlimited | Maximum Tavily credits to spend |
| `--warn-threshold FRACTION` | `0.80` | Warn when budget hits this fraction |
| `--no-scrape` | off | Disable Playwright fallback scraper |
| `--respect-robots` / `--no-respect-robots` | `true` | Advisory robots.txt check |
| `--log-level LEVEL` | `INFO` | Logging verbosity |

LLM settings (model, provider, base URL, API key) are environment-variable only
— see `.env.example` for the full list.

## 9. Run artifacts

All artifacts are written to `--output-dir/<run-id>/`:

| File | Description |
|------|-------------|
| `initial_state.json` | State snapshot before the first Scout call |
| `checkpoint_iter_N.json` | Incremental state after each iteration |
| `final_state.json` | Complete state after workflow finalization |
| `final_report.md` | Markdown synthesis report |
| `knowledge_graph.graphml` | GraphML export of the knowledge graph |
| `knowledge_graph.dot` | Graphviz DOT export |
| `graph_viewer.html` | Self-contained HTML graph viewer with contradictions, gaps, and local resource provenance |

## 10. Automatic resume

If a run is interrupted — network loss, quota exhaustion, power off — simply
re-run the **exact same command**:

```bash
# Re-run — resumes from the latest checkpoint automatically
python -m sensemaking_agent --query "lithium supply chain risks" --output-dir ./data/runs
```

## 11. Dry-run mode

Use `--dry-run` to run the full LangGraph workflow with LLM reasoning but
without any Tavily API calls. Useful for verifying the pipeline offline:

```bash
python -m sensemaking_agent --query "AI safety" --dry-run
```

---

## Contributor Workflow

The sections below are for contributors implementing new features.

### What to read first

1. [README.md](README.md)
2. [.github/copilot-instructions.md](.github/copilot-instructions.md)
3. [docs/prd.md](docs/prd.md)
4. [docs/architecture.md](docs/architecture.md)
5. [docs/state-schema.md](docs/state-schema.md)
6. [docs/sensemaking-loop.md](docs/sensemaking-loop.md)
7. [docs/report-spec.md](docs/report-spec.md)
8. [docs/reuse-from-v1.md](docs/reuse-from-v1.md)
9. [docs/implementation-progress.md](docs/implementation-progress.md)

That sequence moves from product intent to implementation constraints.

### How to use V1 correctly

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

### Implementation task order

1. Check the architecture and state docs before writing code.
2. Confirm the task fits the Scout, Analyst, Critic, Writer, or routing layer.
3. Reuse V1 only at the tool or utility level unless a doc explicitly says otherwise.
4. Prefer structured output contracts before writing free-form prompts.
5. Keep the knowledge graph and contradiction log as first-class outputs.
6. Update docs if implementation reveals a mismatch in the contract.
7. After the code change review the affected docs and update any stale status or
   implementation notes before considering the work done.
8. Update [docs/implementation-progress.md](docs/implementation-progress.md)
   so the repository has a durable handoff point for the next session.

### Running the test suite

```bash
cd sensemaking-agent
python -m pytest tests -q
```

Expected: all tests pass with no live network calls required.

### Environment stack

- Python 3.10+
- LangGraph for orchestration
- Pydantic for structured LLM outputs
- NetworkX for in-memory graph operations
- Tavily for search and extract
- Playwright as the browser fallback
- Ollama or another compatible LLM endpoint for local or remote inference