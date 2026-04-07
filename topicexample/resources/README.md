# Resources

Place plain-text research documents here — Markdown notes, text files, CSVs,
logs, or any other UTF-8 content you want the agent to read directly.

Files can be organized in sub-folders — the loader scans recursively.

## Supported formats

| Extension | Notes |
|-----------|-------|
| `.md`, `.txt`, `.text`, `.rst` | Markdown and plain text |
| `.csv`, `.tsv` | Tabular data |
| `.log` | Log files |

## Complex formats → use graphragloader

For PDF, Word, EPUB, MOBI, source code, images, or other complex document
types, use the `graphragloader` package to build a GraphRAG index **before**
running the agent:

```bash
# From topicexample/
./prepare.sh        # converts resources/ into graphrag/ index
./run.sh            # agent queries GraphRAG + live web search
```

The agent will automatically detect and query the `graphrag/` directory
alongside its web searches — no extra flags needed when using `--topic-dir`.

