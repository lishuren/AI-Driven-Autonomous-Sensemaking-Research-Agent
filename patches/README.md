# patches/

This directory contains patched copies of third-party venv files.
Apply (or re-apply) them after every `pip install` or venv rebuild.

## graphrag_storage — PyArrow ≥ 22 nested-array bug

**Bug**: `ArrowNotImplementedError: Nested data conversions not implemented for
chunked array outputs`

**Trigger**: Reading a Parquet file that (a) contains a column of type
`list<string>` **and** (b) was written with multiple row groups.  GraphRAG's NLP
fast-mode pipeline (`extract_graph_nlp`) writes `relationships.parquet` and
`entities.parquet` in this way.  On large corpora the file can exceed 1 GB with
10+ row groups, which reliably triggers the bug.

**Root cause**: PyArrow ≥ 22.0.0 uses its dataset scanner when reading multi-
row-group files.  The scanner returns `ChunkedArray` columns; converting a
`ChunkedArray` with a nested element type to pandas is not implemented.
`iter_batches()` yields `RecordBatch` objects (non-chunked), which convert
correctly.

**Affected package/version**: `graphrag-storage==3.0.8` with `pyarrow==22.0.0`

**Fixed files** (relative to venv `Lib/site-packages/`):

| Repo path | Venv path |
|-----------|-----------|
| `patches/graphrag_storage/parquet_table_provider.py` | `graphrag_storage/tables/parquet_table_provider.py` |
| `patches/graphrag_storage/parquet_table.py` | `graphrag_storage/tables/parquet_table.py` |

**Change summary**: Every `pd.read_parquet(BytesIO(...))` call was replaced with:

```python
pf = pq.ParquetFile(BytesIO(data))
frames = [batch.to_pandas() for batch in pf.iter_batches()]
df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
```

### Reapply after venv rebuild

```powershell
$venv = "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv"
$pkg  = "$venv\Lib\site-packages\graphrag_storage\tables"
$here = "$PSScriptRoot\graphrag_storage"

Copy-Item "$here\parquet_table_provider.py" "$pkg\parquet_table_provider.py" -Force
Copy-Item "$here\parquet_table.py"          "$pkg\parquet_table.py"          -Force

# Clear compiled cache so Python picks up the new source
Remove-Item "$pkg\__pycache__\parquet_table_provider.cpython-*.pyc" -ErrorAction SilentlyContinue
Remove-Item "$pkg\__pycache__\parquet_table.cpython-*.pyc"          -ErrorAction SilentlyContinue

Write-Host "Patch applied."
```

---

## graphrag_storage — `iterrows()` performance fix

**Bug**: `ParquetTable._aiter_impl()` iterated rows via `pd.DataFrame.iterrows()`,
which creates a full `pd.Series` object per row (~50-100x slower than dict-based
iteration).  On corpora with 9.5M relationship rows this caused `finalize_graph`
to hang for hours (observed: >6 hours without completing).

**Affected package/version**: `graphrag-storage==3.0.8`

**Fixed file** (relative to venv `Lib/site-packages/`):

| Repo path | Venv path |
|-----------|-----------|
| `patches/graphrag_storage/parquet_table.py` | `graphrag_storage/tables/parquet_table.py` |

**Change summary**: In `_aiter_impl`, replaced:

```python
for _, row in self._df.iterrows():
    yield _apply_transformer(...)
```

with:

```python
for row_dict in self._df.to_dict("records"):
    yield _apply_transformer(...)
```

The patch file in `patches/graphrag_storage/parquet_table.py` includes **both**
the PyArrow fix and this performance fix.

---

## graphrag — `finalize_graph` vectorized rewrite

**Bug**: `graphrag.index.workflows.finalize_graph` performed three sequential
full passes over 9.5M rows using `async for row in table:` (which internally
calls `_aiter_impl`):
1. `_build_degree_map()` — full scan to build a `Counter`
2. `finalize_entities()` — full scan to assign IDs and degrees
3. `finalize_relationships()` — full scan to assign IDs and combined degrees

Each pass was O(n) Python-loop overhead.  At 9.5M rows × 3 passes the workflow
never completed within a practical timeframe.

**Affected package/version**: `graphrag==3.0.8`

**Fixed file** (relative to venv `Lib/site-packages/`):

| Repo path | Venv path |
|-----------|-----------|
| `patches/graphrag/index/workflows/finalize_graph.py` | `graphrag/index/workflows/finalize_graph.py` |

**Change summary**: Replaced the three-pass streaming implementation with a
single `_finalize_vectorized()` function that:
- Loads both DataFrames once via `read_dataframe()` (bulk columnar read)
- Builds the degree map with NumPy vectorized `np.where` + `value_counts()`
- Deduplicates and assigns IDs with `drop_duplicates()` + `reset_index()`
- Completes `finalize_graph` in seconds instead of hours

### Reapply after venv rebuild

```powershell
$venv = "D:\Dev\AI-Driven-Autonomous-Sensemaking-Research-Agent\.venv"
$pkgSt  = "$venv\Lib\site-packages\graphrag_storage\tables"
$pkgGr  = "$venv\Lib\site-packages\graphrag\index\workflows"
$here   = $PSScriptRoot

# graphrag_storage patches (PyArrow + iterrows fixes)
Copy-Item "$here\graphrag_storage\parquet_table_provider.py" "$pkgSt\parquet_table_provider.py" -Force
Copy-Item "$here\graphrag_storage\parquet_table.py"          "$pkgSt\parquet_table.py"          -Force

# graphrag finalize_graph vectorized rewrite
New-Item -ItemType Directory -Force -Path "$pkgGr" | Out-Null
Copy-Item "$here\graphrag\index\workflows\finalize_graph.py" "$pkgGr\finalize_graph.py" -Force

# Clear bytecode cache
Remove-Item "$pkgSt\__pycache__\parquet_table_provider.cpython-*.pyc" -ErrorAction SilentlyContinue
Remove-Item "$pkgSt\__pycache__\parquet_table.cpython-*.pyc"          -ErrorAction SilentlyContinue
Remove-Item "$pkgGr\__pycache__\finalize_graph.cpython-*.pyc"         -ErrorAction SilentlyContinue

Write-Host "All patches applied."
```

---

## Development Environment — Windows / VPN

### `Failed to connect to github.com port 443` (Windows + VPN)

Symptom: `git push` / `git pull` fails with:

```
fatal: unable to access 'https://github.com/...': Failed to connect to github.com port 443
```

This typically happens on Windows 10/11 when a VPN is active.  Two independent
causes are common; try them in order.

#### 1 — Stale proxy settings

Git may be caching a proxy that was set for a previous network environment and
is no longer reachable through the VPN.

```powershell
git config --global --unset http.proxy
git config --global --unset https.proxy
```

Verify no proxy remains:

```powershell
git config --global --list | Select-String proxy
```

#### 2 — DNS not resolving `github.com` through the VPN

The VPN tunnel sometimes leaves DNS in a broken state.  From an **elevated**
Command Prompt or PowerShell:

```cmd
ipconfig /flushdns
netsh winsock reset
```

Restart the PC after running both commands so network adapters re-initialise
cleanly.  If the VPN client has a "Reconnect" button, use that first before
rebooting.

