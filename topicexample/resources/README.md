# Resources

Place local research documents here — PDFs, Word files, ebooks (EPUB, MOBI),
Markdown, plain text, source code, or any other literature you want the agent
to incorporate during analysis.

Files can be organized in sub-folders — the converter scans recursively.

## Supported formats

| Extension | Reader |
|-----------|--------|
| `.md`, `.txt`, `.rst`, `.csv`, `.tsv`, `.log`, `.text` | Plain text (stdlib) |
| `.pdf` | LlamaIndex (PyMuPDF) — text extraction with OCR fallback |
| `.docx` | LlamaIndex — paragraph text extraction |
| `.epub` | LlamaIndex — chapter text extraction |
| `.mobi` | mobi library — extract to HTML then strip tags |
| `.pptx` | LlamaIndex — slide text extraction |
| `.ipynb` | LlamaIndex — notebook cell extraction |
| `.jpg`, `.jpeg`, `.png` | LlamaIndex (optional OCR) |
| `.py`, `.js`, `.ts`, `.java`, `.go`, `.rs`, `.c`, `.cpp` | Code analyzer — AST/tree-sitter structural extraction |

## How it works

Resources are indexed into a **GraphRAG knowledge graph** before the agent runs.
The workflow is:

1. Place files in this folder.
2. Run `prepare.ps1` (Windows) or `prepare.sh` (Linux/macOS) from the parent
   directory — this converts files and builds the GraphRAG index in `../graphrag/`.
3. Run `run.ps1` / `run.sh` — the agent queries the GraphRAG index alongside
   live web search via Tavily.

```bash
# From topicexample/
./prepare.sh        # index resources into graphrag/
./run.sh            # run the sensemaking agent
```

## Dependencies

The indexing step requires the `graphragloader` package:

```bash
cd ../graphragloader
pip install -e ".[all]"
```

For OCR of scanned PDFs, [Tesseract](https://github.com/tesseract-ocr/tesseract)
must also be installed on your system and available on `PATH`.
