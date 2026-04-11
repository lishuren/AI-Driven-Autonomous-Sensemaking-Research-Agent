"""Document converter — transforms diverse file types into plain text for GraphRAG.

Uses LlamaIndex ``SimpleDirectoryReader`` as the primary conversion engine,
with custom readers for formats not natively supported.  Each source file is
written as a ``.txt`` file into ``<target>/input/`` so GraphRAG can index it.

Public API
----------
``convert_resources(source_dir, target_dir, *, include_code, max_chars)``
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class ConvertedDocument:
    """Record of a single converted file."""
    source_path: str
    target_path: str
    title: str
    char_count: int
    format: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Extension sets
# ---------------------------------------------------------------------------

# Extensions that LlamaIndex SimpleDirectoryReader handles natively.
_LLAMAINDEX_EXTENSIONS = {
    ".pdf", ".docx", ".epub", ".csv", ".md", ".txt",
    ".pptx", ".ppt", ".pptm",
    ".ipynb",
    ".hwp",
    ".mbox",
}

# Image and audio/video formats: no extractable text, skip silently.
_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp",
    ".svg", ".ico", ".heic", ".heif",
    ".mp3", ".mp4", ".wav", ".ogg", ".flac", ".aac", ".avi", ".mov", ".mkv",
}

# Plain text extensions we handle directly (fast, no deps).
_PLAINTEXT_EXTENSIONS = {
    ".md", ".txt", ".text", ".rst", ".csv", ".tsv", ".log",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".xml", ".html", ".htm",
}

# Source code extensions (handled by code_analyzer when include_code=True).
_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".java", ".cs", ".go", ".rs",
    ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp",
    ".rb", ".php", ".swift", ".kt", ".scala",
    ".sh", ".bash", ".ps1", ".bat",
    ".sql", ".r", ".m", ".lua",
    ".Makefile", ".Dockerfile",
}

# Excel formats handled by _read_excel().
_EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsb", ".xlsm", ".odf", ".ods", ".odt"}

# Archive formats we can extract and recurse into.
_ARCHIVE_EXTENSIONS = {".zip"}

# Binary/media extensions that cannot be usefully read as text.
_SKIP_EXTENSIONS = {
    ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
    ".iso", ".img", ".dmg",
    ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".db", ".sqlite", ".sqlite3",
}

_MAX_CONTENT_CHARS = 200_000

# MOBI support (optional dependency).
_HAS_MOBI = False
try:
    import mobi as _mobi_lib  # noqa: F401
    _HAS_MOBI = True
except ImportError:
    pass

_HAS_BS4 = False
try:
    from bs4 import BeautifulSoup  # noqa: F401
    _HAS_BS4 = True
except ImportError:
    pass

_HAS_PANDAS = False
try:
    import pandas as _pd  # noqa: F401
    _HAS_PANDAS = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stable_filename(source_path: Path) -> str:
    """Build a stable, collision-resistant output filename."""
    digest = hashlib.sha1(str(source_path.resolve()).encode()).hexdigest()[:12]
    stem = re.sub(r"[^\w\-.]", "_", source_path.stem)[:60]
    return f"{stem}_{digest}.txt"


def _is_up_to_date(source: Path, output_dir: Path) -> bool:
    """Return True when the output .txt already exists and is newer than source."""
    out_path = output_dir / _stable_filename(source)
    if not out_path.exists():
        return False
    try:
        return source.stat().st_mtime <= out_path.stat().st_mtime
    except OSError:
        return False


def _read_mobi(path: Path) -> Optional[str]:
    """Extract text from a MOBI ebook."""
    if not _HAS_MOBI:
        logger.info(
            "converter: skipping MOBI %s — mobi library not installed.  "
            "Install with: pip install 'graphragloader[mobi]'",
            path,
        )
        return None

    import mobi as _mobi  # noqa: WPS433

    try:
        tmpdir, extracted_path = _mobi.extract(str(path))
    except Exception as exc:
        logger.warning("converter: cannot extract MOBI %s — %s", path, exc)
        return None

    try:
        extracted = Path(extracted_path)
        if not extracted.exists():
            logger.warning("converter: MOBI extraction produced no output — %s", path)
            return None

        raw = extracted.read_text(encoding="utf-8", errors="replace")

        if _HAS_BS4:
            from bs4 import BeautifulSoup as _BS  # noqa: WPS433
            return _BS(raw, "html.parser").get_text(separator="\n", strip=True) or None

        # Minimal fallback: strip HTML tags.
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
        return text or None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _read_plaintext(path: Path) -> Optional[str]:
    """Read a file as plain UTF-8 text."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("converter: cannot read %s — %s", path, exc)
        return None


def _read_excel(path: Path, max_chars: int = _MAX_CONTENT_CHARS) -> Optional[str]:
    """Convert an Excel workbook into text (one section per sheet).

    Reads sheets one at a time and stops early once accumulated text already
    exceeds *max_chars*. Caps each sheet at *_EXCEL_MAX_ROWS* rows to avoid
    spending minutes loading a massive sheet that will be truncated anyway.
    """
    if not _HAS_PANDAS:
        logger.info(
            "converter: skipping Excel %s — pandas not installed.  "
            "Install with: pip install 'graphragloader[excel]'",
            path,
        )
        return None

    import pandas as pd  # noqa: WPS433

    # Row cap: each row is typically 50–500 chars; 2,000 rows comfortably
    # covers 100,000 chars while keeping read time under a second for most files.
    _EXCEL_MAX_ROWS = 2000

    try:
        xf = pd.ExcelFile(path)
        sheet_names = xf.sheet_names
    except Exception as exc:
        logger.warning("converter: cannot open Excel %s — %s", path, exc)
        return None

    parts: list[str] = []
    accumulated = 0

    for sheet_name in sheet_names:
        if accumulated >= max_chars:
            logger.debug(
                "converter: %s — stopping at sheet '%s' (char limit reached)",
                path.name, sheet_name,
            )
            break
        try:
            df = xf.parse(sheet_name, dtype=str, nrows=_EXCEL_MAX_ROWS)
        except Exception as exc:
            logger.warning("converter: skipping sheet '%s' in %s — %s", sheet_name, path.name, exc)
            continue
        if df.empty:
            continue
        header = f"## Sheet: {sheet_name}\n\n"
        table = df.fillna("").to_csv(sep="\t", index=False)
        chunk = header + table
        parts.append(chunk)
        accumulated += len(chunk)

    return "\n\n".join(parts) if parts else None


def _extract_zip(
    archive_path: Path,
    output_dir: Path,
    max_chars: int,
    *,
    include_code: bool = False,
    force: bool = False,
) -> list[ConvertedDocument]:
    """Extract a ZIP archive into a temp dir and convert its contents."""
    try:
        if not zipfile.is_zipfile(archive_path):
            logger.warning("converter: not a valid ZIP — %s", archive_path)
            return []
    except OSError as exc:
        logger.warning("converter: cannot open ZIP %s — %s", archive_path, exc)
        return []

    tmpdir = Path(tempfile.mkdtemp(prefix="graphragloader_zip_"))
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            # Guard against zip bombs: limit total extracted size to 500 MB.
            total_size = sum(info.file_size for info in zf.infolist())
            if total_size > 500 * 1024 * 1024:
                logger.warning(
                    "converter: ZIP %s too large (%d bytes uncompressed) — skipping",
                    archive_path, total_size,
                )
                return []
            zf.extractall(tmpdir)

        # Recurse into the extracted directory.  We call the internal
        # _convert_files helper directly to avoid creating a separate
        # output dir.
        return _convert_files(
            source_dir=tmpdir,
            output_dir=output_dir,
            max_chars=max_chars,
            include_code=include_code,
            force=force,
            _archive_prefix=archive_path.name,
            _track_progress=False,  # top-level call owns the progress file
        )
    except Exception as exc:
        logger.warning("converter: failed to process ZIP %s — %s", archive_path, exc)
        return []
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _looks_binary(text: str, *, sample_size: int = 1024) -> bool:
    """Heuristic: return True if *text* looks like decoded binary garbage."""
    sample = text[:sample_size]
    if not sample:
        return False
    # Count characters outside the printable ASCII + common Unicode range.
    non_text = sum(1 for c in sample if c != '\n' and c != '\r' and c != '\t' and (ord(c) < 32 or ord(c) == 0xFFFD))
    return (non_text / len(sample)) > 0.3


def _build_metadata_header(path: Path) -> str:
    """Build a metadata header prepended to each output text file."""
    return (
        f"Source: {path.name}\n"
        f"Path: {path.resolve()}\n"
        f"Format: {path.suffix.lstrip('.')}\n"
        f"---\n\n"
    )


def _use_llamaindex(source_dir: Path, extensions: set[str], *, files: Optional[list[Path]] = None) -> dict[str, str]:
    """Use LlamaIndex to read files matching *extensions* from *source_dir*.

    When *files* is provided, only those specific files are loaded (incremental
    mode).  Otherwise the full *source_dir* is scanned recursively.

    Returns a mapping of ``{resolved_path_str: extracted_text}``.
    """
    try:
        from llama_index.core import SimpleDirectoryReader
    except ImportError:
        logger.warning(
            "converter: llama-index-core not installed — cannot read rich formats.  "
            "Install with: pip install 'graphragloader'"
        )
        return {}

    # Filter to only extensions that LlamaIndex can handle.
    target_exts = sorted(extensions & _LLAMAINDEX_EXTENSIONS)
    if not target_exts:
        return {}

    try:
        if files:
            # Load only the specific files that need (re-)processing.
            reader = SimpleDirectoryReader(
                input_files=[str(f) for f in files],
                errors="ignore",
            )
        else:
            reader = SimpleDirectoryReader(
                input_dir=str(source_dir),
                recursive=True,
                required_exts=target_exts,
                errors="ignore",
            )
        documents = reader.load_data()
    except Exception as exc:
        logger.warning("converter: LlamaIndex load failed — %s", exc)
        return {}

    results: dict[str, str] = {}
    for doc in documents:
        file_path = (doc.metadata or {}).get("file_path", "")
        if not file_path:
            continue
        # LlamaIndex may split a file into multiple documents; concatenate.
        key = str(Path(file_path).resolve())
        existing = results.get(key, "")
        text = doc.text or ""
        results[key] = (existing + "\n\n" + text).strip() if existing else text

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def convert_resources(
    source_dir: str | Path,
    target_dir: str | Path,
    *,
    include_code: bool = False,
    max_chars: int = _MAX_CONTENT_CHARS,
    force: bool = False,
) -> list[ConvertedDocument]:
    """Convert all supported files in *source_dir* to text in ``<target_dir>/input/``.

    Parameters
    ----------
    source_dir:
        Directory containing local resource files (scanned recursively).
    target_dir:
        GraphRAG project root.  Converted text files are placed in
        ``<target_dir>/input/``.
    include_code:
        If ``True``, source code files are analysed and converted via
        ``code_analyzer``.  Requires the ``[code]`` optional dependency.
    max_chars:
        Maximum characters per output file.  Longer content is truncated.

    Returns
    -------
    list[ConvertedDocument]
        One record per successfully converted file.
    """
    src = Path(source_dir)
    if not src.is_dir():
        logger.warning("converter: source directory does not exist — %s", src)
        return []

    output_dir = Path(target_dir) / "input"
    output_dir.mkdir(parents=True, exist_ok=True)

    results = _convert_files(
        source_dir=src,
        output_dir=output_dir,
        max_chars=max_chars,
        include_code=include_code,
        force=force,
    )
    skipped = sum(1 for r in results if r.metadata.get("skipped"))
    if skipped:
        logger.info(
            "converter: %d / %d files skipped (output already up to date)",
            skipped, len(results),
        )
    # Clean up progress file when the run completes.
    progress_file = output_dir.parent / ".convert_progress"
    try:
        progress_file.unlink(missing_ok=True)
    except OSError:
        pass
    return results


def _convert_files(
    source_dir: Path,
    output_dir: Path,
    max_chars: int,
    *,
    include_code: bool = False,
    force: bool = False,
    _archive_prefix: Optional[str] = None,
    _track_progress: bool = True,
) -> list[ConvertedDocument]:
    """Internal: convert all files in *source_dir*, write to *output_dir*."""
    # Discover all files.
    all_files = sorted(
        f for f in source_dir.rglob("*")
        if f.is_file() and not f.name.startswith(".")
    )
    if not all_files:
        logger.info("converter: no files found in %s", source_dir)
        return []

    # ── Progress tracking ────────────────────────────────────────────────────
    # Write a .convert_progress JSON file to the target root so external
    # tools (e.g. check_status.ps1) can see which file is being processed.
    _progress_file = output_dir.parent / ".convert_progress" if _track_progress else None
    _progress_total = len(all_files)
    _progress_done = [0]
    _progress_interval = max(1, _progress_total // 500)   # ~500 updates per run
    _progress_start = time.strftime("%Y-%m-%d %H:%M:%S")
    _last_log_time = [time.monotonic()]
    _LOG_INTERVAL_S = 30  # log to console at most every 30 s

    logger.info(
        "converter: starting — %d files to process (source: %s)",
        _progress_total, source_dir,
    )

    def _tick(current: Path) -> None:
        _progress_done[0] += 1
        n = _progress_done[0]
        now = time.monotonic()
        should_write = n == 1 or n % _progress_interval == 0 or n >= _progress_total
        should_log   = (now - _last_log_time[0]) >= _LOG_INTERVAL_S or n >= _progress_total

        if should_write and _progress_file is not None:
            try:
                _progress_file.write_text(
                    json.dumps({
                        "current": str(current),
                        "done": n,
                        "total": _progress_total,
                        "pct": round(100.0 * n / _progress_total, 1),
                        "started": _progress_start,
                    }),
                    encoding="utf-8",
                )
            except OSError:
                pass

        if should_log:
            _last_log_time[0] = now
            pct = round(100.0 * n / _progress_total, 1)
            logger.info(
                "converter: %d / %d files (%.1f%%)  current: %s",
                n, _progress_total, pct, current,
            )

    # Partition files by handling strategy.
    llamaindex_exts: set[str] = set()
    plaintext_files: list[Path] = []
    mobi_files: list[Path] = []
    code_files: list[Path] = []
    excel_files: list[Path] = []
    archive_files: list[Path] = []
    fallback_files: list[Path] = []
    llamaindex_candidates: list[Path] = []

    for f in all_files:
        ext = f.suffix.lower()
        # Normalise Makefile/Dockerfile (no extension).
        if f.name in ("Makefile", "Dockerfile"):
            ext = f".{f.name}"

        if include_code and ext in _CODE_EXTENSIONS:
            code_files.append(f)
        elif ext == ".mobi":
            mobi_files.append(f)
        elif ext in _EXCEL_EXTENSIONS:
            excel_files.append(f)
        elif ext in _ARCHIVE_EXTENSIONS:
            archive_files.append(f)
        elif ext in _PLAINTEXT_EXTENSIONS:
            plaintext_files.append(f)
        elif ext in _LLAMAINDEX_EXTENSIONS:
            llamaindex_exts.add(ext)
            llamaindex_candidates.append(f)
        elif ext in _PLAINTEXT_EXTENSIONS | _CODE_EXTENSIONS:
            # Treat unrecognised code as plain text when include_code is False.
            plaintext_files.append(f)
        elif ext in _SKIP_EXTENSIONS or ext in _IMAGE_EXTENSIONS:
            logger.debug("converter: skipping binary/media file %s", f.name)
        else:
            # Unknown extension — try reading as plain text.
            fallback_files.append(f)

    results: list[ConvertedDocument] = []

    # Phase 1: LlamaIndex for rich formats (PDF, DOCX, EPUB, etc.)
    # Pre-filter: skip files whose output is already up to date (avoids loading
    # potentially thousands of PDFs/DOCXs through LlamaIndex unnecessarily).
    if not force:
        lli_skip = [f for f in llamaindex_candidates if _is_up_to_date(f, output_dir)]
        lli_need = [f for f in llamaindex_candidates if not _is_up_to_date(f, output_dir)]
        if lli_skip:
            logger.info(
                "converter: phase 1/7 — LlamaIndex  skipping %d / %d already up-to-date files",
                len(lli_skip), len(llamaindex_candidates),
            )
            for f in lli_skip:
                _tick(f)
                results.append(ConvertedDocument(
                    source_path=str(f.resolve()),
                    target_path=str((output_dir / _stable_filename(f)).resolve()),
                    title=f.name, char_count=0,
                    format=f.suffix.lstrip(".") or "txt",
                    metadata={"size_bytes": f.stat().st_size, "skipped": True},
                ))
    else:
        lli_need = llamaindex_candidates

    if lli_need:
        logger.info(
            "converter: phase 1/7 — LlamaIndex  (%d files: %s)  [this may take several minutes]",
            len(lli_need), ", ".join(sorted(llamaindex_exts)),
        )
    llamaindex_results = _use_llamaindex(source_dir, llamaindex_exts, files=lli_need) if lli_need else {}
    if lli_need:
        logger.info("converter: phase 1/7 — LlamaIndex done (%d results)", len(llamaindex_results))

    # Write LlamaIndex results.
    for f in lli_need:
        _tick(f)
        key = str(f.resolve())
        text = llamaindex_results.get(key, "")
        if not text or not text.strip():
            logger.debug("converter: LlamaIndex produced no text for %s — skipping", f.name)
            continue
        results.append(
            _write_output(f, text, output_dir, max_chars, force=force)
        )

    # Phase 2: plain text files (no deps needed).
    if plaintext_files:
        logger.info("converter: phase 2/7 — plain text  (%d files)", len(plaintext_files))
    for f in plaintext_files:
        _tick(f)
        text = _read_plaintext(f)
        if not text or not text.strip():
            continue
        results.append(
            _write_output(f, text, output_dir, max_chars, force=force)
        )

    # Phase 3: MOBI files.
    if mobi_files:
        logger.info("converter: phase 3/7 — MOBI  (%d files)", len(mobi_files))
    for f in mobi_files:
        _tick(f)
        text = _read_mobi(f)
        if not text or not text.strip():
            continue
        results.append(
            _write_output(f, text, output_dir, max_chars, force=force)
        )

    # Phase 4: Excel files.
    if excel_files:
        logger.info("converter: phase 4/7 — Excel  (%d files)", len(excel_files))
    for f in excel_files:
        _tick(f)
        text = _read_excel(f, max_chars=max_chars)
        if not text or not text.strip():
            continue
        results.append(
            _write_output(f, text, output_dir, max_chars, fmt="excel", force=force)
        )

    # Phase 5: ZIP archives (recursive extraction).
    if archive_files:
        logger.info("converter: phase 5/7 — ZIP archives  (%d files)", len(archive_files))
    for f in archive_files:
        _tick(f)
        extracted = _extract_zip(f, output_dir, max_chars, include_code=include_code, force=force)
        results.extend(extracted)

    # Phase 6: source code (when requested).
    if code_files and include_code:
        logger.info("converter: phase 6/7 — source code  (%d files)", len(code_files))
        try:
            from .code_analyzer import analyze_code_files
            for f in code_files:
                _tick(f)
                text = analyze_code_files(f)
                if text and text.strip():
                    results.append(
                        _write_output(f, text, output_dir, max_chars, fmt="code", force=force)
                    )
        except ImportError:
            logger.info(
                "converter: code_analyzer not available — treating %d code files as plain text.",
                len(code_files),
            )
            for f in code_files:
                _tick(f)
                text = _read_plaintext(f)
                if text and text.strip():
                    results.append(
                        _write_output(f, text, output_dir, max_chars, fmt="code", force=force)
                    )

    # Phase 7: unknown extensions — try reading as plain text.
    if fallback_files:
        logger.info("converter: phase 7/7 — fallback plain-text  (%d files)", len(fallback_files))
    for f in fallback_files:
        _tick(f)
        text = _read_plaintext(f)
        if text and text.strip():
            # Check if the content looks like binary garbage.
            if _looks_binary(text):
                logger.debug("converter: %s appears binary — skipping", f.name)
                continue
            results.append(
                _write_output(f, text, output_dir, max_chars, fmt="txt", force=force)
            )
        else:
            logger.debug("converter: no usable text from %s — skipping", f.name)

    label = f" (from {_archive_prefix})" if _archive_prefix else ""
    logger.info(
        "converter: converted %d files from %s%s → %s",
        len(results), source_dir, label, output_dir,
    )
    return results


def _write_output(
    source: Path,
    text: str,
    output_dir: Path,
    max_chars: int,
    *,
    fmt: str | None = None,
    force: bool = False,
) -> ConvertedDocument:
    """Write a single converted document to the output directory."""
    out_name = _stable_filename(source)
    out_path = output_dir / out_name

    # Incremental mode: skip files whose output is already up to date.
    if not force and out_path.exists():
        try:
            if source.stat().st_mtime <= out_path.stat().st_mtime:
                logger.debug("converter: %s — output up to date, skipping", source.name)
                return ConvertedDocument(
                    source_path=str(source.resolve()),
                    target_path=str(out_path.resolve()),
                    title=source.name,
                    char_count=0,
                    format=fmt or source.suffix.lstrip(".") or "txt",
                    metadata={"size_bytes": source.stat().st_size, "skipped": True},
                )
        except OSError:
            pass  # If stat fails, fall through and re-convert.

    if len(text) > max_chars:
        text = text[:max_chars]
        logger.warning("converter: truncated %s to %d chars.", source.name, max_chars)

    header = _build_metadata_header(source)
    full_text = header + text

    out_path.write_text(full_text, encoding="utf-8")

    return ConvertedDocument(
        source_path=str(source.resolve()),
        target_path=str(out_path.resolve()),
        title=source.name,
        char_count=len(text),
        format=fmt or source.suffix.lstrip(".") or "txt",
        metadata={"size_bytes": source.stat().st_size},
    )
