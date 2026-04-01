# Topic Example: Maintaining a Legacy .NET C# Product

This folder is a self-contained example demonstrating the **topic directory**
convention used by the AI-Driven Autonomous Sensemaking Research Agent.

## Folder layout

```
topicexample/
├── .env                     ← API keys and budget limits (gitignored)
├── .env.example             ← template — copy to .env and fill in your keys
├── .gitignore               ← ignores .env and output/
├── requirements.md          ← research topic spec (auto-discovered)
├── prompts/
│   ├── analyst_extract.md   ← domain-tuned entity/triplet extraction prompt
│   ├── critic_analyze.md    ← domain-tuned contradiction/gap detection prompt
│   └── writer_synthesize.md ← domain-tuned final report synthesis prompt
├── resources/               ← local PDFs, Word docs, text files (optional)
│   └── README.md
├── output/                  ← created automatically; all run artifacts go here
├── run.ps1                  ← Windows PowerShell run script
├── run.sh                   ← Linux/macOS bash run script
└── README.md                ← this file
```

## How it works

Pass `--topic-dir` pointing at this folder and the agent handles everything:

| Convention | What happens |
|------------|--------------|
| `requirements.md` | Parsed for `## Topic` (query), `## Research Focus`, and `## Background` (context injected into all LLM prompts) |
| `prompts/` | Overrides the bundled prompt templates |
| `resources/` | Local documents (PDF, DOCX, Markdown, text) are loaded as seed documents into the knowledge graph before the first web search |
| `output/` | Auto-created; run artifacts and reports are written here |
| `.env` | Loaded automatically; sets API keys and budget limits for this topic |

No `--output-dir`, `--prompt-dir`, or `--query` flags needed.

## Setup

### 1. Fill in your API keys

Edit `.env` in this folder with your Tavily key and LLM provider credentials.

### 2. Verify credit balance (optional)

```bash
cd ../sensemaking-agent
python check_tavily_usage.py
```

### 3. Add local resources (optional)

Place any PDFs, Word documents, or text files in `resources/`.  The agent reads
them automatically and feeds them into the analysis pipeline.

PDF and Word support requires optional dependencies:

```bash
cd ../sensemaking-agent
pip install ".[resources]"
```

## Run

### Windows (PowerShell)

```powershell
.\run.ps1
```

### Linux/macOS (bash)

```bash
./run.sh
```

### Manual command

From `sensemaking-agent/`:

```bash
python -m sensemaking_agent --topic-dir ../topicexample --max-iterations 4
```

### Dry run (no Tavily calls, offline test)

```bash
python -m sensemaking_agent --topic-dir ../topicexample --max-iterations 2 --dry-run
```

---

## Output

Artifacts are written to `topicexample/output/<run-id>/`:

| File | Description |
|------|-------------|
| `final_report.md` | Markdown synthesis: executive summary, key pillars, disputed facts, gaps |
| `knowledge_graph.graphml` | GraphML — open in yEd, Gephi, or Cytoscape |
| `knowledge_graph.dot` | Graphviz DOT — render with `dot -Tpng knowledge_graph.dot -o graph.png` |
| `graph_viewer.html` | Open in a browser — interactive HTML graph viewer |
| `final_state.json` | Full machine-readable state including all triplets and entities |

### Resuming an interrupted run

If the run is interrupted (network loss, quota exhaustion), re-run the **exact
same command**. The agent detects the latest checkpoint in `output/` and
continues from where it left off.

---

## How the custom prompts work

The `prompts/` subfolder contains domain-tuned overrides for all three LLM nodes:

### `analyst_extract.md`

Overrides the generic analyst prompt with one that knows about:
- .NET-specific entity types: `tool`, `framework`, `pattern`, `vulnerability`, `lifecycle_event`
- Domain-appropriate predicates: `mitigates`, `patches`, `vulnerable_to`, `supports_until`,
  `wraps`, `isolates`, `deprecates`
- Instructions to extract CVE-to-mitigation pairs and lifecycle dates explicitly

### `critic_analyze.md`

Overrides the generic critic prompt to prioritize contradictions that matter most for
a developer's real decisions:
- Conflicting end-of-support dates → `severity: high`
- Conflicting security guidance → `severity: high`
- Missing CVE mitigations → research gap `priority: high`

### `writer_synthesize.md`

Overrides the generic writer prompt to produce a practitioner guide:
- Audience framing: software developer needing actionable guidance, not a summary
- Key pillars mapped to known maintenance categories: "Environment Freezing",
  "Security Hardening", "Integration Strategies"
- Emphasis on specific tool names and version numbers

---

## Customizing for your own topic

To adapt this example for a different topic:

1. Update `requirements.md` with your topic and background.
2. Adjust the entity types and predicates in `prompts/analyst_extract.md` for
   your domain (e.g., for a medical topic: `drug`, `condition`, `trial`, `contraindicated_with`).
3. Adjust the contradiction priorities in `prompts/critic_analyze.md` for what
   matters most in your domain.
4. Update the `key_pillars` guidance in `prompts/writer_synthesize.md` to
   reflect how experts in your field structure knowledge.
5. Set a realistic budget in `.env` based on the scope of the topic.
