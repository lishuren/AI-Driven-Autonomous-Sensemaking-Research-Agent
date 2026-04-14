# GraphRAG Mainstream Analysis — Resume-by-Default Guide

## Core Design Principle: Resume Is Always the Default

**You should never need a flag to resume.  Just re-run the script.**

Every step that was already completed is skipped automatically on every re-run.
To start fresh you delete the relevant marker file — there is no "reset" flag.

| Step | Skip condition (auto-detected) | To force a fresh start |
|------|-------------------------------|------------------------|
| Convert | `.convert_done.json` exists | `Remove-Item D:\mainstreamGraphRAG\.convert_done.json` |
| Index | `.shard_status.json` has `#completed = true` | `Remove-Item D:\mainstreamGraphRAG\.shard_status.json`; `Remove-Item D:\mainstreamGraphRAG\output -Recurse` |
| Each report | `reports\<name>.md` exists | `Remove-Item D:\mainstreamGraphRAG\reports\<name>.md` |

Repeatable within-run steps that are always re-executed (each ≤2 min):
- Model warm-up (Ollama `api/ps` poll)
- NLTK data check
- settings.yaml model patch

These are fast enough that repeating them every run is not a problem.

## Overview

The scripts orchestrate a three-step GraphRAG workflow for long-running jobs:

1. **Convert** — Transform source docs into GraphRAG input (30–40 min, one-time)
2. **Index** — GraphRAG extract_graph, build, compute (8–10 days for standard; 48–72 h for fast mode)
3. **Reports** — Generate 5 analysis documents via LLM queries

## How Resume Works

### Convert step
- Writes `.convert_done.json` on completion.
- On every subsequent run the script detects this file and skips convert.

### Index step
- Writes `.shard_status.json` with `"#completed": true` after a successful full index.
- When this marker is present the index phase is skipped entirely (no model warm-up either).
- When it is absent but `output/` has subdirectories from a previous partial run, `--resume` is automatically appended to the `graphrag index` command so GraphRAG continues from the last completed workflow.

### Report step
- Each report writes its own `.md` file under `reports/`.
- On re-run, any report whose `.md` already exists is skipped — only missing or deleted reports are regenerated.

## Usage Patterns

### First Run (Full Workflow)
```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1"
```
Runs: convert → index → reports (full 8–10+ days)

### Interrupted / Crashed — Just Re-Run
```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1"
```
No flags needed.  The script auto-detects what was completed and resumes.

### Check Status Without Running
```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -CheckShardStatus
```
- No workflow steps execute.
- Displays index completion status.
- Exit code 0 (non-destructive).

### Regenerate a Single Report
```powershell
Remove-Item "D:\mainstreamGraphRAG\reports\analysis_report.md"
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1"
```
All other reports are skipped; only the deleted one is regenerated.

## Loss Boundary & Recovery

### Granularity: ~100 Rows Per Resume Cycle
- Extract_graph processes 30,108 total text units
- Cache preserves completed LLM request/response pairs
- On Ctrl+C, ~100 rows of in-flight computation is lost (worst case)
- `--resume` is passed automatically on restart so GraphRAG skips already-completed workflow steps; only in-progress workflow rows are re-computed

### Cache Mechanism
- LiteLLM stores request/response pairs in `D:\mainstreamGraphRAG\cache`
- Ollama embedding and completion cache is automatically leveraged
- Cache is always preserved across re-runs (nothing deletes it)
- Recomputation of cached rows is near-instant (no API calls)

### Logs & Checkpoints
- Main log: `D:\mainstreamGraphRAG\run_mainstream_analysis.log`
- Completion marker: `D:\mainstreamGraphRAG\.shard_status.json`
- Each restart appends to log with timestamp and run context
- Extract_graph progress is traceable via indexing-engine.log

## Workflow Timeline & Expectations

| Phase | Duration | Notes |
|-------|----------|-------|
| Convert | 30–40 min | One-time, unless source changes |
| Extract_graph | 8–10 days | Longest phase, most loss-prone |
| Build | 1–2 hours | Graph structure construction |
| Compute | 2–4 hours | Centrality & community detection |
| Reports | 30–60 min | 5 LLM queries, sequential |
| **Total** | **~10 days** | Assuming uninterrupted |

## Fast Processing Mode (48–72 h Target)

For large corpora (100k+ files / 10+ GB), `run_mainstream_fast.ps1` applies three knobs
that together cut the number of LLM calls to roughly one-third of the standard run.

### What changes vs. the standard script

| Setting | Standard | Fast | Effect |
|---|---|---|---|
| Max chars / file | 500,000 | **100,000** | ~5× fewer chars ingested |
| GraphRAG method | standard | **fast** | lighter extraction algorithm |
| Chunk size (tokens) | 1,200 | **2,000** | ~40% fewer text units |
| Chunk overlap | 100 | **150** | — |
| Indexing model | gemma4:e4b | **gemma4:e2b** | fits fully in 8 GB VRAM |
| Report model | gemma4:e4b | **gemma4:e4b** | unchanged — quality preserved |
| Log file | `run_mainstream_analysis.log` | **`run_mainstream_fast.log`** | separate, no clobber |

### Dual-Model Strategy

The fast script uses **two different models** in sequence:

1. **`gemma4:e2b` — indexing** (entity extraction, ~10k–18k LLM calls)
   - 2.3 B effective / 5.1 B total parameters
   - ~4.5 GB on disk — fits entirely in 8 GB VRAM with ~3 GB headroom
   - No CPU offload means every call runs at full GPU speed
   - Structured extraction quality is sufficient for code/doc corpora

2. **`gemma4:e4b` — report generation** (5 queries total)
   - Higher-quality synthesis for the final reports
   - Runs after indexing is complete; only 5 LLM calls so latency is tolerable

The script patches `settings.yaml` automatically between the two phases —
no manual YAML edits needed.

### Prerequisites

Pull the indexing model before the first run (e4b is already installed):

```powershell
ollama pull gemma4:e2b
```

### Usage

**First run (full: convert + index + reports):**
```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_fast.ps1"
```

**Resume after interruption:**
```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_fast.ps1" -SkipConvert
```

**Reports only (after index completes):**
```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_fast.ps1" -SkipConvert -SkipIndex
```

**Override either model independently:**
```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_fast.ps1" `
    -IndexModel "gemma4:e2b" `
    -ReportModel "gemma4:e4b"
```

### Fast-Mode Timeline Estimate

| Phase | Duration | Notes |
|---|---|---|
| Convert | 5–10 min | 100k char cap reduces output size |
| Extract_graph | 30–48 h | e2b + fast method + fewer chunks |
| Build / Compute | 2–4 h | unchanged |
| Reports | 30–60 min | e4b model, 5 queries |
| **Total** | **~48–72 h** | With uninterrupted Ollama |

> **Quality tradeoff:** Fast mode extracts fewer entities per text unit and may miss
> low-frequency relationships. For a first-pass analysis of a large repo, this is
> usually acceptable. Use the standard script for production-quality deep analysis.

---

## Adding New Source Code to Analysis

If you have been granted access to a new repository and want to include it in the GraphRAG index,
follow these steps. Because convert must re-run to pick up the new files, **do not use `-SkipConvert`** for this workflow.

### Step 1 — Copy or Clone the Repo into the Source Folder

`D:\Mainstream` is the root source folder. Add sub-folders inside it however suits your workflow.

**Option A — Clone directly:**
```powershell
git clone https://github.com/your-org/your-repo.git "D:\Mainstream\your-repo"
```

**Option B — Copy a local checkout:**
```powershell
Copy-Item -Path "C:\path\to\your\repo" -Destination "D:\Mainstream\your-repo" -Recurse
```

The loader walks all sub-folders recursively, so any nesting level is fine.

### Step 2 — (Optional) Preview What Will Be Converted

Run convert in isolation to verify your code files appear before committing to the full index:

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv\Scripts\graphragloader.exe" convert `
    --source "D:\Mainstream" `
    --target "D:\mainstreamGraphRAG" `
    --include-code `
    --max-chars 500000
```

Inspect `D:\mainstreamGraphRAG\input` — each document is written as a plain-text file. Confirm your
source files were picked up before starting the long index run.

### Step 3 — Run the Full Workflow

```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1"
```

This runs: convert (re-processes all of `D:\Mainstream`) → index → reports.

> **Cache note:** The existing LLM cache in `D:\mainstreamGraphRAG\cache` still covers
> previously indexed text units, so those units incur no extra model calls. Only the
> newly added code files are processed from scratch.

### Supported Source Code File Types

The loader recognises these extensions automatically (no extra flags needed):

| Language | Extensions |
|----------|-----------|
| Python | `.py` |
| JavaScript / TypeScript | `.js`, `.ts`, `.tsx` |
| Java | `.java` |
| C# | `.cs` |
| Go | `.go` |
| Rust | `.rs` |
| C / C++ | `.c`, `.cpp`, `.h` |
| SQL | `.sql` |
| Shell / PowerShell | `.sh`, `.ps1` |
| Config / Markup | `.yaml`, `.toml`, `.json`, `.xml`, `.html`, `.md` |

Unknown extensions are tried as plain text; binary-looking content is skipped automatically.

---

## Best Practices

### Preventing Accidental Loss
1. **Check status before restarting:**
   ```powershell
   & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -CheckShardStatus
   ```

2. **Always use `-SkipConvert` after first run:**
   ```powershell
   # After Ctrl+C:
   & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -SkipConvert
   
   # NOT:
   # & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1"  # <-- This would re-run convert, slower
   ```

3. **Avoid deleting cache folder:**
   - Do NOT delete `D:\mainstreamGraphRAG\cache` between runs
   - Do NOT delete `D:\mainstreamGraphRAG\input` (unless re-converting)
   - Deleting these forces full recomputation

### Monitoring Progress
- Watch `run_mainstream_analysis.log` for real-time status:
  ```powershell
  Get-Content "D:\mainstreamGraphRAG\run_mainstream_analysis.log" -Wait
  ```

- Check indexing engine log for extract_graph detail:
  ```powershell
  Get-Content "D:\mainstreamGraphRAG\logs\indexing-engine.log" -Wait -Tail 50
  ```

### Environment Stability for 10-Day Runs
- The wrapper now attempts to auto-start `ollama serve` if the API is down at launch
- Required Ollama models must still be pulled in advance: `gemma4:e4b` and `nomic-embed-text`
- The wrapper forces `LITELLM_LOCAL_MODEL_COST_MAP=True` so LiteLLM uses its bundled model metadata instead of timing out on a GitHub fetch during startup
- Once indexing starts, keep Ollama running for the duration of the run (no restarts)
- Verify network stability (Tavily API, local network)
- Disable auto-sleep / hibernation on the machine
- Monitor disk space (index grows to ~5–10 GB)

## Configuration

Settings are stored in `D:\mainstreamGraphRAG\settings.yaml`:

```yaml
completion_models:
  default_completion_model:
    model_provider: ollama_chat
    model: gemma4:e4b
    api_base: http://localhost:11434
    timeout: 1800

embedding_models:
  default_embedding_model:
    model_provider: ollama
    model: nomic-embed-text
    api_base: http://localhost:11434
    timeout: 1800

chunking:
  size: 1200
  overlap: 100

vector_store: lancedb
```

Key tuning:
- `timeout: 1800` — 30 min per LLM call (adequate for long Ollama graph extraction calls)
- `chunking.size: 1200` — 1200 tokens per chunk (balanced for gemma4)
- `GraphMethod = standard` in the wrapper — GraphRAG indexing mode (do not change)

## Troubleshooting

### Checkpoint Lost / Restart Recomputes Everything
**Symptom:** Restarting with `-SkipConvert` retarts extract_graph from row ~5, not from prior stopping point.

**Root Cause:** Workflow checkpoints (`.shard_status.json`) differ from LLM response cache. Cache is preserved; index state is not.

**Solution:** This is expected. Use cache-aware resumption:
```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -SkipConvert
# Index reprocesses, but LLM cache hits make it fast
```

### Reports Not Generated After Index Completes
**Symptom:** Index completes, but reports folder remains empty.

**Symptom:** Graphics crashes during convert or index, reports not attempted.

**Solution:** Run report step only:
```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -SkipConvert -SkipIndex
```

### Ollama Timeout During extract_graph
**Symptom:** "Request timeout after 1800 seconds" in logs during index phase.

**Solution:** Increase timeout in settings.yaml:
```yaml
completion_models:
  default_completion_model:
    timeout: 3600  # 60 min (was 30 min)

embedding_models:
  default_embedding_model:
    timeout: 3600
```

### Ollama Server Not Running or Models Missing
**Symptom:** The wrapper exits before indexing begins with an Ollama startup or missing-model error.

**Behavior:** `run_mainstream_analysis.ps1` now attempts to start `ollama serve` automatically if the API is down at launch. It also fails fast if `gemma4:e4b` or `nomic-embed-text` is not installed.

### LiteLLM Remote Cost-Map Warning
**Symptom:** Startup logs show a warning like `LiteLLM: Failed to fetch remote model cost map ... Falling back to local backup.`

**Behavior:** This warning is non-fatal. LiteLLM only uses that remote file for model pricing/context metadata and automatically falls back to the packaged backup JSON. The wrapper now sets `LITELLM_LOCAL_MODEL_COST_MAP=True` so the offline/local Ollama workflow skips the remote fetch entirely.

**Solution:** Pull the required models once, then rerun:
```powershell
ollama pull gemma4:e4b
ollama pull nomic-embed-text

& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -SkipConvert
```

## Files & Paths

| Path | Purpose |
|------|---------|
| `D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1` | Main workflow script |
| `D:\Mainstream` | Source document folder |
| `D:\mainstreamGraphRAG` | Target GraphRAG project folder |
| `D:\mainstreamGraphRAG\input` | Converted text units (from convert step) |
| `D:\mainstreamGraphRAG\output` | Index artifacts (parquet, json, db) |
| `D:\mainstreamGraphRAG\cache` | LLM response cache (Ollama responses) |
| `D:\mainstreamGraphRAG\reports` | Final Markdown reports (5 files) |
| `D:\mainstreamGraphRAG\.shard_status.json` | Checkpoint file (created by script) |
| `D:\mainstreamGraphRAG\run_mainstream_analysis.log` | Workflow log (appended on each run) |
| `D:\mainstreamGraphRAG\settings.yaml` | GraphRAG configuration |
| `D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_fast.ps1` | Fast-processing script (48–72 h) |
| `D:\mainstreamGraphRAG\run_mainstream_fast.log` | Fast-mode workflow log |

## Next Steps

1. **First run:**
   ```powershell
   & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1"
   ```
   Expected: Runs for 8–10 days, generates 5 reports.

2. **On interruption, resume:**
   ```powershell
   & "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -SkipConvert
   ```
   Expected: ~100-row loss, cache-accelerated recomputation.

3. **Check progress anytime:**
   ```powershell
   Get-Content "D:\mainstreamGraphRAG\run_mainstream_analysis.log" -Wait
   ```

---

**Last Updated:** 2026-04-10  
**Script Version:** 2.2 (dual-model fast processing)  
**Supported Scripts:** `run_mainstream_analysis.ps1` (standard, ~10 days) | `run_mainstream_fast.ps1` (fast, ~48–72 h)  
**Changelog:**
- Added `run_mainstream_fast.ps1` with dual-model strategy (e2b for indexing, e4b for reports)
- Added "Fast Processing Mode" section and fast-mode timeline
- Added "Adding New Source Code to Analysis" section
