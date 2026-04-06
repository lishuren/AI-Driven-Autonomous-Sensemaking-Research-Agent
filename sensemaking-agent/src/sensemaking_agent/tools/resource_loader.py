"""Local resource loader — reads plain-text files from a ``resources/`` directory.

Supported formats (no external dependencies required):

* ``.md``, ``.txt``, ``.text``, ``.rst`` — Markdown and plain text
* ``.csv``, ``.tsv``, ``.log``           — tabular data and logs

For complex document formats (PDF, DOCX, EPUB, MOBI) or source code, use the
``graphragloader`` package to build a GraphRAG index first, then point the
agent at the resulting ``graphrag/`` directory with ``--graphrag-dir``.

Directory scanning is **recursive** — sub-folders are traversed.

Each file becomes a ``SourceDocument`` with ``source_type="local_resource"``,
``acquisition_method="file_read"``, and ``url="file://…"``.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from ..state import SourceDocument

logger = logging.getLogger(__name__)

_TEXT_EXTENSIONS = {".md", ".txt", ".text", ".rst", ".csv", ".tsv", ".log"}
_MAX_CONTENT_CHARS = 80_000  # generous raw limit; individual nodes truncate further


def _read_text_file(path: Path) -> Optional[str]:
    """Read a plain text file."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("resource_loader: cannot read %s — %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _document_id(path: Path) -> str:
    """Derive a stable document ID from file path and modification time."""
    stat = path.stat()
    key = f"{path.resolve()}::{stat.st_mtime_ns}"
    return "doc_res_" + hashlib.sha1(key.encode()).hexdigest()[:16]


def load_resources(resources_dir: str | Path) -> list[SourceDocument]:
    """Read all supported plain-text files from *resources_dir* and return ``SourceDocument`` list.

    The directory is scanned **recursively** — sub-folders are traversed.
    Unsupported extensions are silently skipped with a debug log.

    For complex formats (PDF, DOCX, EPUB, MOBI, source code), use the
    ``graphragloader`` package to pre-index them into a GraphRAG directory.
    """
    base = Path(resources_dir)
    if not base.is_dir():
        logger.warning("resource_loader: directory does not exist — %s", base)
        return []

    results: list[SourceDocument] = []

    for entry in sorted(base.rglob("*")):
        if not entry.is_file():
            continue

        ext = entry.suffix.lower()
        content: Optional[str] = None

        if ext in _TEXT_EXTENSIONS:
            content = _read_text_file(entry)
        else:
            logger.debug("resource_loader: skipping unsupported file %s", entry.name)
            continue

        if not content or not content.strip():
            logger.debug("resource_loader: empty content from %s — skipping", entry.name)
            continue

        # Truncate excessively large content.
        if len(content) > _MAX_CONTENT_CHARS:
            content = content[:_MAX_CONTENT_CHARS]
            logger.warning(
                "resource_loader: truncated %s to %d chars.", entry.name, _MAX_CONTENT_CHARS
            )

        doc = SourceDocument(
            document_id=_document_id(entry),
            url=entry.resolve().as_uri(),
            title=entry.name,
            content=content,
            source_type="local_resource",
            query="",  # not query-driven
            acquisition_method="file_read",
            metadata={"original_path": str(entry.resolve()), "size_bytes": entry.stat().st_size},
        )
        results.append(doc)

    logger.info("resource_loader: loaded %d documents from %s.", len(results), base)
    return results
