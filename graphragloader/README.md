# graphragloader

Convert diverse local files (PDF, DOCX, EPUB, images, video, source code, etc.)
into a [GraphRAG](https://microsoft.github.io/graphrag/) knowledge graph.

## Quick Start

```bash
pip install -e ".[all]"

# Convert resources and build the GraphRAG index
graphragloader index --source ./resources --target ./graphrag

# Query the index
graphragloader query --target ./graphrag --question "What are the key findings?"
```

## Operations Runbook

For Windows-focused operational guidance (dependency issues, long-run indexing,
warnings, and troubleshooting), see [RUNBOOK.md](RUNBOOK.md).

For a quick shell-based runtime check against a GraphRAG target directory, run:

```bash
./check_status.sh /path/to/graphrag-project
```

For a native PowerShell runtime check on Windows, run:

```powershell
.\check_status.ps1 D:\mainstreamGraphRAG
```

## Supported File Types

| Category | Extensions |
|----------|-----------|
| Text | `.md`, `.txt`, `.rst`, `.csv`, `.tsv`, `.log`, `.json`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, `.xml`, `.html` |
| Documents | `.pdf`, `.docx`, `.epub`, `.mobi`, `.pptx` |
| Spreadsheets | `.xlsx`, `.xls`, `.xlsb`, `.xlsm`, `.ods` |
| Notebooks | `.ipynb` |
| Images | `.jpg`, `.jpeg`, `.png` |
| Audio/Video | `.mp3`, `.mp4` |
| Archives | `.zip` (extracted and contents converted recursively) |
| Source Code | `.py`, `.js`, `.ts`, `.tsx`, `.java`, `.cs`, `.go`, `.rs`, `.c`, `.cpp`, `.h`, `.sql`, `.ps1`, `.sh`, … |
| Unknown | Any unrecognized extension is tried as plain text; binary-looking content is skipped |

## CLI Commands

- `graphragloader init` — generate GraphRAG settings.yaml
- `graphragloader convert` — convert files to text (no indexing)
- `graphragloader index` — convert + build GraphRAG index
- `graphragloader query` — query an existing GraphRAG index

## Helper Scripts

- `check_status.sh` — inspect a GraphRAG target directory and show whether a matching indexing process is currently running
- `check_status.ps1` — PowerShell version of the status helper for Windows terminals. Always shows a deduplicated **Running GraphRAG jobs** summary at the bottom, listing every active `graphrag index`, `graphragloader convert`, or `graphragloader query` job across all targets (not just the one being checked). The `Status` field reflects only the specified target.

## Optional Dependencies

| Extra | Provides |
|-------|----------|
| `[excel]` | `.xls`, `.xlsx` support via pandas + openpyxl + xlrd |
| `[code]` | Structural code analysis via tree-sitter |
| `[ocr]` | OCR for scanned PDFs via pytesseract |
| `[mobi]` | `.mobi` ebook support |
| `[all]` | Everything above plus dev tools |
