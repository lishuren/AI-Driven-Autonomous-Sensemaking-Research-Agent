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
