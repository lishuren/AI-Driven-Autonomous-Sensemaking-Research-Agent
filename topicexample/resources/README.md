# Resources

Place local research documents here — PDFs, Word files, ebooks (EPUB, MOBI),
Markdown, plain text, or any other literature you want the agent to
incorporate during analysis.

Files can be organized in sub-folders — the agent scans recursively.

## Supported formats

| Extension | Reader |
|-----------|--------|
| `.md`, `.txt`, `.rst`, `.csv`, `.tsv`, `.log`, `.text` | Standard text (stdlib) |
| `.pdf` | PyMuPDF — text extraction with OCR fallback for scanned pages |
| `.docx` | python-docx — paragraph text extraction |
| `.epub` | ebooklib + BeautifulSoup — chapter text extraction |
| `.mobi` | mobi library — extract to HTML then strip tags |

## How it works

When the agent is launched with `--topic-dir` pointing to the parent folder,
any files found here are loaded as seed documents into the knowledge graph
**before** the first web search.  The Analyst will extract entities and
relationships from these local documents just as it does for web results.

## Optional dependencies

PDF and Word support require optional packages:

```bash
cd ../sensemaking-agent
pip install ".[resources]"
```

This installs `pymupdf`, `python-docx`, `pytesseract`, and `Pillow`.  If these
packages are not installed, the agent will skip unsupported file types and log a
warning.

For OCR of scanned PDFs, [Tesseract](https://github.com/tesseract-ocr/tesseract)
must also be installed on your system and available on `PATH`.
