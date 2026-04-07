# GraphRAG Mainstream Analysis — Shard Checkpoint & Resume Guide

## Overview

The `run_mainstream_analysis.ps1` script orchestrates a three-step GraphRAG workflow with built-in checkpoint recovery for long-running jobs:

1. **Convert** — Transform D:\Mainstream docs into GraphRAG input (30–40 min, one-time)
2. **Index** — GraphRAG extract_graph, build, compute (8–10 days, most prone to interruption)
3. **Reports** — Generate 5 analysis documents via LLM queries

## Key Improvements

### Shard Checkpoint Tracking
- After index completes, status is saved to `.shard_status.json` in the target folder
- On restart, the script detects prior checkpoints and logs resumption context
- Checkpoint records timestamp and completion state

### Resume Flags
- **`-SkipConvert`** — Skip the convert step, reuse existing input, resume index from prior checkpoint
- **`-CheckShardStatus`** — Query-only mode; shows last checkpoint without running any workflow step
- **`-SkipIndex`** — Skip indexing, regenerate reports only (assumes index output exists)

### Auto-Resume Guidance
If index is interrupted:
- Script logs checkpoint timestamp
- On script exit, displays resumption instructions automatically
- Clear one-liner command to re-run with cache intact

## Usage Patterns

### First Run (Full Workflow)
```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1"
```
Runs: convert → index → reports (full 8–10+ days)

### Interrupted by Ctrl+C During Index
```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -SkipConvert
```
- Skips convert (saves 30–40 min)
- Resumes index near prior stopping point
- Input folder and cache reused
- Projected loss window: ~100 rows of in-flight work

### Check Status Without Running
```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -CheckShardStatus
```
- No workflow steps execute
- Displays last checkpoint timestamp
- Shows resumption command
- Exit code 0 (non-destructive)

### Regenerate Reports Only (After Index Complete)
```powershell
& "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\run_mainstream_analysis.ps1" -SkipConvert -SkipIndex
```
- Skips both convert and index
- Runs only report generation (Step 3)
- Useful if reports fail but index succeeded

## Loss Boundary & Recovery

### Granularity: ~100 Rows Per Resume Cycle
- Extract_graph processes 30,108 total text units
- Cache preserves completed LLM request/response pairs
- On Ctrl+C, ~100 rows of in-flight computation is lost (worst case)
- Subsequent resume benefits from full cache hit on prior 30,008 rows

### Cache Mechanism
- LiteLLM stores request/response pairs in `D:\mainstreamGraphRAG\cache`
- Ollama embedding and completion cache is automatically leveraged
- Resume with `-SkipConvert` preserves this cache
- Recomputation of cached rows is near-instant (no API calls)

### Logs & Checkpoints
- Main log: `D:\mainstreamGraphRAG\run_mainstream_analysis.log`
- Checkpoint file: `D:\mainstreamGraphRAG\.shard_status.json`
- Each resume appends to log with timestamp and checkpoint info
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
- Ensure Ollama stays running (no restarts)
- Verify network stability (Tavily API, local network)
- Disable auto-sleep / hibernation on the machine
- Monitor disk space (index grows to ~5–10 GB)

## Configuration

Settings are stored in `D:\mainstreamGraphRAG\settings.yaml`:

```yaml
llm:
  api_key: ""
  type: ollama
  model: gemma4:e4b
  request_timeout: 1800

embedding:
  type: ollama
  model: nomic-embed-text

chunking:
  size: 1200
  overlap: 100

graphrag:
  method: standard  # Do not change
  max_depth: 2

vector_store: lancedb
```

Key tuning:
- `request_timeout: 1800` — 30 min per LLM call (adequate for 10-day window)
- `chunking.size: 1200` — 1200 tokens per chunk (balanced for gemma4)
- `method: standard` — GraphRAG indexing mode (do not change)

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
llm:
  request_timeout: 3600  # 60 min (was 30 min)
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

**Last Updated:** 2026-04-08  
**Script Version:** 2.0 (shard checkpoint + resume)  
**Supported Commands:** Full | `-SkipConvert` | `-SkipIndex` | `-CheckShardStatus` | combinations
