"""GraphRAG indexing wrapper — converts + indexes local resources.

Provides both a programmatic Python API (using ``graphrag.api.build_index``)
and a subprocess fallback (using ``graphrag index`` CLI).

Public API
----------
``async index(target_dir, *, source_dir, include_code, method, force, settings_config)``
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_STATE_FILE = ".graphragloader_state.json"


@dataclass
class IndexResult:
    """Result of a GraphRAG indexing run."""
    success: bool
    target_dir: str
    documents_converted: int = 0
    method: str = "standard"
    error: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)


def _compute_file_hashes(directory: Path) -> dict[str, str]:
    """Compute SHA-256 hashes for all files in a directory."""
    hashes: dict[str, str] = {}
    if not directory.is_dir():
        return hashes
    for f in sorted(directory.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            h = hashlib.sha256(f.read_bytes()).hexdigest()
            hashes[str(f.relative_to(directory))] = h
    return hashes


def _load_state(target_dir: Path) -> dict[str, Any]:
    """Load the indexer state from the target directory."""
    state_path = target_dir / _STATE_FILE
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(target_dir: Path, state: dict[str, Any]) -> None:
    """Save the indexer state to the target directory."""
    state_path = target_dir / _STATE_FILE
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _needs_reindex(source_dir: Path, target_dir: Path) -> bool:
    """Check if the source files have changed since the last index."""
    state = _load_state(target_dir)
    prev_hashes = state.get("file_hashes", {})
    curr_hashes = _compute_file_hashes(source_dir)
    return prev_hashes != curr_hashes


def _parse_settings_for_threshold(settings_path: Path) -> dict[str, int]:
    """Parse a minimal set of values from `settings.yaml` used to compute split thresholds.

    Returns a dict with keys: `chunk_size`, `overlap`, `batch_size`, `batch_max_tokens`.
    Uses sensible defaults when keys are missing.
    """
    defaults = {"chunk_size": 2000, "overlap": 150, "batch_size": 8, "batch_max_tokens": 2000}
    if not settings_path.exists():
        return defaults
    try:
        text = settings_path.read_text(encoding="utf-8")
    except OSError:
        return defaults

    def _find_int(pattern: str, default: int) -> int:
        m = re.search(pattern, text, flags=re.MULTILINE)
        if not m:
            return default
        try:
            return int(m.group(1))
        except Exception:
            return default

    chunk_size = _find_int(r"^\s*size:\s*(\d+)", defaults["chunk_size"])
    overlap = _find_int(r"^\s*overlap:\s*(\d+)", defaults["overlap"])
    batch_size = _find_int(r"^\s*batch_size:\s*(\d+)", defaults["batch_size"])
    batch_max_tokens = _find_int(r"^\s*batch_max_tokens:\s*(\d+)", defaults["batch_max_tokens"])

    return {
        "chunk_size": chunk_size,
        "overlap": overlap,
        "batch_size": batch_size,
        "batch_max_tokens": batch_max_tokens,
    }


def _auto_split_input_files(target_dir: Path, max_chars: int, force: bool = False) -> dict[str, list[str]]:
    """Naively split large text files in `input/` into `_partN.txt` files.

    - Skips files that already match `_part\d+` unless `force=True`.
    - Returns a mapping of original -> list of created part file paths.
    """
    input_dir = target_dir / "input"
    out: dict[str, list[str]] = {}
    if not input_dir.exists():
        return out

    for f in sorted(input_dir.rglob("*.txt")):
        name = f.name
        base = f.stem
        ext = f.suffix

        # skip hidden and marker files
        if name.startswith("."):
            continue

        # Skip already-split files unless forcing or they remain too large
        is_part = re.search(r"_part\d+$", base)
        try:
            size = f.stat().st_size
        except OSError:
            continue

        if is_part and not force and size <= max_chars:
            continue

        if not force and size <= max_chars:
            continue

        # Read content and split on line boundaries to preserve readability
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        parts: list[str] = []
        if len(text) <= max_chars:
            # nothing to do
            continue

        # Build parts by accumulating lines
        cur = []
        cur_len = 0
        part_no = 1
        for line in text.splitlines(keepends=True):
            l = len(line)
            if cur_len + l > max_chars and cur:
                part_name = f"{base}_part{part_no}{ext}"
                part_path = f.parent / part_name
                part_path.write_text("".join(cur), encoding="utf-8")
                parts.append(str(part_path))
                part_no += 1
                cur = [line]
                cur_len = l
            else:
                cur.append(line)
                cur_len += l

        if cur:
            part_name = f"{base}_part{part_no}{ext}"
            part_path = f.parent / part_name
            part_path.write_text("".join(cur), encoding="utf-8")
            parts.append(str(part_path))

        # Remove original file after successful split
        try:
            f.unlink()
        except OSError:
            # best-effort; continue
            pass

        if parts:
            out[str(f)] = parts

    return out


async def _attempt_index_with_auto_split(target_dir: Path, *, method: str = "standard", verbose: bool = False) -> IndexResult:
    """Attempt to run the Python indexing API with automatic splitting and retries.

    Strategy:
    - Pre-split large input files based on `chunk_size` parsed from settings.
    - Run `_run_index_api`.
    - On embedding-size errors, reduce max_chars and re-split (up to a few retries).
    - On connection errors/timeouts, retry with backoff.
    """
    settings_path = target_dir / "settings.yaml"
    vals = _parse_settings_for_threshold(settings_path)
    chunk_size = vals.get("chunk_size", 2000)

    # heuristic: assume ~4 chars per token
    chars_per_token = 4
    max_chars = max(2000, int(chunk_size * chars_per_token))

    # initial pre-split
    _auto_split_input_files(target_dir, max_chars, force=False)

    max_retries = 3
    last_result: Optional[IndexResult] = None
    for attempt in range(max_retries):
        result = await _run_index_api(target_dir, method=method, verbose=verbose)
        if result.success:
            return result

        last_result = result
        err_text = (result.error or "") + " " + json.dumps(result.details or {})
        low = err_text.lower()

        # Detect embedding size errors and attempt to split smaller
        if "exceed" in low or "context length" in low or "input length" in low:
            # reduce threshold and re-split existing files
            new_max = max(800, max_chars // 2)
            if new_max >= max_chars:
                break
            max_chars = new_max
            _auto_split_input_files(target_dir, max_chars, force=True)
            await asyncio.sleep(2 ** attempt)
            continue

        # Detect connection/refused/timeout and retry with backoff
        if any(k in low for k in ("refused", "10061", "timeout", "timed out", "connection reset")):
            await asyncio.sleep(2 ** attempt)
            continue

        # Unrecognized error — give up and return
        break

    return last_result or IndexResult(success=False, target_dir=str(target_dir), method=method, error="Indexing failed after retries.")


async def index(
    target_dir: str | Path,
    *,
    source_dir: Optional[str | Path] = None,
    include_code: bool = False,
    method: str = "standard",
    force: bool = False,
    settings_config: Optional[Any] = None,
    verbose: bool = False,
) -> IndexResult:
    """Convert source files and run GraphRAG indexing.

    Parameters
    ----------
    target_dir:
        GraphRAG project root (contains settings.yaml, input/, output/).
    source_dir:
        Directory containing raw resource files.  If provided, files are
        first converted to text via ``converter.convert_resources()``.
        If ``None``, assumes ``<target_dir>/input/`` already has content.
    include_code:
        Pass through to ``convert_resources``.
    method:
        GraphRAG indexing method: ``"standard"`` (LLM) or ``"fast"`` (NLP).
    force:
        Force re-indexing even if source files haven't changed.
    settings_config:
        Optional ``SettingsConfig`` for generating ``settings.yaml``.
    verbose:
        Enable verbose logging.

    Returns
    -------
    IndexResult
    """
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    docs_converted = 0

    # Step 1: Convert source files if a source_dir is provided.
    if source_dir is not None:
        src = Path(source_dir)
        if not force and not _needs_reindex(src, target):
            logger.info("indexer: source files unchanged — skipping conversion (use force=True)")
        else:
            from .converter import convert_resources
            results = convert_resources(src, target, include_code=include_code)
            docs_converted = len(results)
            # Save file hashes.
            state = _load_state(target)
            state["file_hashes"] = _compute_file_hashes(src)
            _save_state(target, state)

    # Step 2: Ensure settings.yaml exists.
    settings_path = target / "settings.yaml"
    if not settings_path.exists():
        from .settings import generate_settings
        generate_settings(target, config=settings_config, force=False)

    # Step 3: Check input/ directory has content.
    input_dir = target / "input"
    if not input_dir.is_dir() or not any(input_dir.iterdir()):
        return IndexResult(
            success=False,
            target_dir=str(target),
            documents_converted=docs_converted,
            method=method,
            error="No documents in input/ directory — nothing to index.",
        )

    # Step 4: Run GraphRAG indexing with auto-split+retry helper.
    try:
        result = await _attempt_index_with_auto_split(target, method=method, verbose=verbose)
    except Exception:
        logger.info("indexer: Python API not available or raised error, falling back to CLI")
        result = await _run_index_cli(target, method=method, verbose=verbose)

    result.documents_converted = docs_converted
    return result


async def _run_index_api(
    target_dir: Path,
    *,
    method: str = "standard",
    verbose: bool = False,
) -> IndexResult:
    """Run indexing via ``graphrag.api.build_index``."""
    from graphrag.api import build_index
    from graphrag.config.load_config import load_config

    config = load_config(target_dir)

    outputs = await build_index(
        config=config,
        method=method,
        verbose=verbose,
    )

    errors = [o.error for o in outputs if o.error is not None]
    if errors:
        return IndexResult(
            success=False,
            target_dir=str(target_dir),
            method=method,
            error="; ".join(str(e) for e in errors),
            details={"workflows_completed": len(outputs) - len(errors)},
        )

    return IndexResult(
        success=True,
        target_dir=str(target_dir),
        method=method,
        details={"workflows_completed": len(outputs)},
    )


async def _run_index_cli(
    target_dir: Path,
    *,
    method: str = "standard",
    verbose: bool = False,
) -> IndexResult:
    """Run indexing via the ``graphrag index`` CLI as a subprocess."""
    cmd = [
        sys.executable, "-m", "graphrag", "index",
        "--root", str(target_dir),
        "--method", method,
    ]
    if verbose:
        cmd.append("--verbose")

    loop = asyncio.get_event_loop()
    proc = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour timeout
        ),
    )

    if proc.returncode != 0:
        return IndexResult(
            success=False,
            target_dir=str(target_dir),
            method=method,
            error=proc.stderr.strip() or f"graphrag index exited with code {proc.returncode}",
            details={"stdout": proc.stdout[-2000:] if proc.stdout else ""},
        )

    return IndexResult(
        success=True,
        target_dir=str(target_dir),
        method=method,
        details={"stdout": proc.stdout[-500:] if proc.stdout else ""},
    )
