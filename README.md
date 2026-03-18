# AI-Driven Autonomous Sensemaking Research Agent

> **V2** of [AI-Driven-Autonomous-Research-Agent](https://github.com/lishuren/AI-Driven-Autonomous-Research-Agent)

A C# / .NET 10 console application that transforms a single research query into a richly interconnected **Knowledge Graph** and a structured research brief — without ever settling for simple summarisation.

Instead of the classic "Search → Summarise" pipeline, this agent runs a **cyclic, self-correcting loop** (modelled after [LangGraph](https://github.com/langchain-ai/langgraph)) that:

- Extracts **entities and relationship triplets** from every scraped document.
- Detects and logs **contradictions** between sources (Dialectical Reasoning).
- Recursively fills **research gaps** by launching targeted follow-up searches.
- Renders the final graph as an **interactive D3.js HTML visualisation**.

---

## Architecture

```
User Query
    │
    ▼
┌─────────┐     ┌──────────┐     ┌─────────┐
│  Scout  │────▶│ Analyst  │────▶│ Critic  │
│(Scraper)│     │(Triplets)│     │(Gaps /  │
└─────────┘     └──────────┘     │Contradic│
     ▲                           └────┬────┘
     │                                │
     │   High-severity contradiction  │
     │   or ResearchGaps remaining    │
     └────────────────────────────────┘
                                       │
                    Graph saturated    │
                    or max iterations  ▼
                               ┌──────────┐
                               │  Writer  │
                               │ (Brief)  │
                               └──────────┘
                                       │
                                       ▼
                            ResearchBrief + knowledge_graph.html
```

### Agent Nodes

| Node | Class | Responsibility |
|------|-------|----------------|
| **Scout** | `ResearchScraper` (`Tools.cs`) | Tavily search; falls back to DuckDuckGo HTML search when `TAVILY_API_KEY` is not set |
| **Analyst** | `AnalystNode` (`Nodes.cs`) | LLM-driven entity and triplet extraction |
| **Critic** | `CriticNode` (`Nodes.cs`) | Contradiction detection, research-gap identification |
| **Writer** | `WriterNode` (`Nodes.cs`) | Graph-to-narrative synthesis into a research brief |

### Routing Logic (`Graph.cs`)

After every **Scout → Analyst → Critic** pass the router (`ShouldContinue`) decides:

1. **High-severity contradiction** found **and** `IterationCount < 3` and `TieBreakerDispatched` is `false` → generate a targeted "tie-breaker" query, set `TieBreakerDispatched = true`, loop back to Scout.
2. **ResearchGaps** not empty **and** `IterationCount < 5` → set `CurrentQuery` to the next gap, loop back to Scout.
3. **Graph saturated** (< 10 % new triplets) **or** `IterationCount ≥ 5` → route to Writer.

### Knowledge Graph

The `KnowledgeGraph` is the single source of truth. The Writer reads **graph edges (triplets)**, not raw document text, to produce its report. This ensures every claim in the brief is traceable to a source.

---

## Prerequisites

| Requirement | Version |
|-------------|---------|
| [.NET SDK](https://dotnet.microsoft.com/download) | 10.0 or later |
| OpenAI API key | — |
| Tavily API key *(optional)* | — |

---

## Setup

1. **Clone the repository**

   ```bash
   git clone https://github.com/lishuren/AI-Driven-Autonomous-Sensemaking-Research-Agent.git
   cd AI-Driven-Autonomous-Sensemaking-Research-Agent
   ```

2. **Set environment variables**

   | Variable | Required | Description |
   |----------|----------|-------------|
   | `OPENAI_API_KEY` | ✅ | Used by Analyst, Critic, and Writer nodes |
   | `TAVILY_API_KEY` | ⬜ | Enables Tavily search (recommended); when absent, Scout falls back to DuckDuckGo HTML search |
   | `OPENAI_BASE_URL` | ⬜ | Override for Azure OpenAI or compatible endpoints (default: `https://api.openai.com/v1`) |
   | `OPENAI_MODEL` | ⬜ | Model name (default: `gpt-4o`) |
   | `SCRAPER_MAX_RESULTS` | ⬜ | Max search results per query (default: `5`) |

   **Linux / macOS**

   ```bash
   export OPENAI_API_KEY="sk-..."
   export TAVILY_API_KEY="tvly-..."
   ```

   **Windows (PowerShell)**

   ```powershell
   $env:OPENAI_API_KEY = "sk-..."
   $env:TAVILY_API_KEY = "tvly-..."
   ```

---

## Build & Run

```bash
cd SensemakingAgent
dotnet run -- "The impact of solid-state batteries on the EV supply chain"
```

If no query is passed as an argument, the agent prompts for one interactively:

```bash
dotnet run
# Enter your research query: The impact of solid-state batteries on the EV supply chain
```

### Example console output

```
╔═══════════════════════════════════════════════════════╗
║   Autonomous Sensemaking Research Agent  v1.0        ║
║   https://github.com/lishuren/                       ║
║   AI-Driven-Autonomous-Sensemaking-Research-Agent    ║
╚═══════════════════════════════════════════════════════╝

[Graph] Starting Sensemaking loop for: "solid-state batteries EV supply chain"
[Graph] Max iterations: 5

[Graph] ── Iteration 1 ── Scout: "solid-state batteries EV supply chain"
[Graph] Scout returned 5 document(s).
[Analyst] Extracted 18 triplets, 12 entities.
[Critic] Found 2 contradiction(s), 3 gap(s).
[Router] High-severity contradiction → Tie-Breaker Scout.
...
[Graph] → Routing to Writer.

═══════════════════════════════════════════════════════
  AUTONOMOUS SENSEMAKING RESEARCH BRIEF
═══════════════════════════════════════════════════════

── EXECUTIVE SUMMARY ──────────────────────────────────
...
── KNOWLEDGE MAP ───────────────────────────────────────
...
── KEY PILLARS ─────────────────────────────────────────
  • Pillar 1: ...
...
Open 'knowledge_graph.html' in a browser to explore the interactive graph.
```

---

## Knowledge Graph Visualisation

After the run, open **`knowledge_graph.html`** (generated in the working directory) in any modern browser.

- 🔵 **Blue nodes** — regular entities
- 🔴 **Red nodes** — entities involved in at least one contradiction
- Hover over a node to see all its direct relationships and the supporting evidence.
- Nodes are draggable; the layout is powered by [D3.js](https://d3js.org/) force-directed simulation.

---

## Project Structure

```
SensemakingAgent/
├── Program.cs        – Entry point; banner, query input, cancellation, visualisation
├── Graph.cs          – SensemakingGraph: state-machine orchestrator + routing logic
├── Nodes.cs          – AnalystNode, CriticNode, WriterNode + LlmGateway
├── State.cs          – ResearchState, KnowledgeGraph, Triplet, Contradiction types
├── Tools.cs          – ResearchScraper (Tavily + DuckDuckGo fallback)
└── Visualizer.cs     – D3.js HTML knowledge-graph generator
```

---

## GraphRAG

Yes — this project is a **GraphRAG** implementation.

[GraphRAG](https://arxiv.org/abs/2404.16130) (Graph Retrieval-Augmented Generation) replaces flat
vector search with a *Knowledge Graph* as the retrieval index.  Instead of finding the most similar
text chunks, an LLM reads **graph edges** (triplets) to produce answers that are grounded in
explicit, traceable relationships.

### How GraphRAG is applied here

| GraphRAG concept | Where it lives |
|------------------|----------------|
| **Entity extraction** | `AnalystNode` — LLM identifies named entities from scraped pages |
| **Relationship extraction** | `AnalystNode` — LLM maps directed `Subject → Predicate → Object` triplets, each with a `source_url` for full traceability |
| **Knowledge Graph construction** | `KnowledgeGraph` in `State.cs` — append-only; duplicates are deduplicated on `(Subject, Predicate, Object)` |
| **Graph-based synthesis** | `WriterNode` — report is generated from graph entities + triplets, **not** raw document text |
| **Iterative graph enrichment** | `SensemakingGraph` loop — Scout → Analyst → Critic repeats until the graph saturates (< 10 % new triplets) |
| **Contradiction detection** | `CriticNode` — flags conflicting triplets with `High`/`Low` severity and triggers tie-breaker searches |
| **Graph visualisation** | `Visualizer.cs` — interactive D3.js force-directed graph; contradicted nodes shown in red |

---

## How It Differs from V1

| Feature | V1 (Search-and-Summarise) | V2 (Sensemaking) |
|---------|--------------------------|------------------|
| Output | Text summary | Knowledge Graph + Research Brief |
| Loop | Linear (single pass) | Cyclic (self-correcting) |
| Contradiction handling | Ignored / averaged | Logged with severity; triggers tie-breaker search |
| Research gaps | Not addressed | Auto-detected; recursive sub-searches |
| Synthesis source | Raw document text | Graph edges (triplets) |
| Visualisation | None | Interactive D3.js force-directed graph |

---

## License

[MIT](LICENSE)
