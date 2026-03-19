"""Prompt file loader for the sensemaking agent.

Searches for prompt files in a custom directory first, then falls back to
the bundled ``prompts/`` directory alongside the package root.

Adapted from the V1 prompt_loader pattern.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def bundled_prompt_dir() -> Path:
    """Return the bundled ``prompts/`` directory for this package.

    Resolves relative to this file's location:
    ``src/sensemaking_agent/prompt_loader.py`` → ``../../prompts/``
    (i.e. ``sensemaking-agent/prompts/``).
    """
    return (Path(__file__).resolve().parent.parent.parent / "prompts").resolve()


def load_prompt(name: str, prompt_dir: Optional[str] = None) -> str:
    """Load the prompt file named *name*.

    Search order:
    1. ``prompt_dir / name`` when *prompt_dir* is provided.
    2. The bundled ``prompts/`` directory.

    Parameters
    ----------
    name:
        Filename, e.g. ``"analyst_extract.md"``.
    prompt_dir:
        Optional path to a custom prompt directory.

    Raises
    ------
    FileNotFoundError
        When the file is not found in any search location.
    """
    search_paths: list[Path] = []
    if prompt_dir:
        search_paths.append(Path(prompt_dir) / name)
    search_paths.append(bundled_prompt_dir() / name)

    for path in search_paths:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()

    searched = ", ".join(str(p) for p in search_paths)
    raise FileNotFoundError(f"Prompt file not found: {name!r} (searched: {searched})")
