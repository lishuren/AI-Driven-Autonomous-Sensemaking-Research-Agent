"""GraphRAG settings generator — produces ``settings.yaml`` for a target project.

Supports two main LLM provider configurations:
- **Ollama** (local): uses ``ollama_chat`` model provider with ``nomic-embed-text`` for embeddings.
- **OpenAI** (or compatible API like SiliconFlow): uses ``openai`` model provider.

Public API
----------
``generate_settings(target_dir, *, llm_provider, llm_model, ...)``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SettingsConfig:
    """Parameters for GraphRAG settings.yaml generation."""

    # LLM provider: "ollama" or "openai" (or any LiteLLM-compatible provider).
    llm_provider: str = "ollama"
    llm_model: str = "gemma4:e4b"
    llm_api_base: Optional[str] = None
    llm_api_key: Optional[str] = None

    # Embedding model.
    embedding_provider: Optional[str] = None  # defaults to llm_provider
    embedding_model: Optional[str] = None     # defaults based on provider
    embedding_api_base: Optional[str] = None
    embedding_api_key: Optional[str] = None

    # Input/output.
    input_type: str = "text"         # text, csv, json
    input_dir: str = "input"
    output_dir: str = "output"

    # Chunking.
    chunk_size: int = 1200
    chunk_overlap: int = 100

    # Graph extraction.
    entity_types: list[str] = field(default_factory=lambda: [
        "organization", "person", "technology", "concept", "event", "location",
    ])
    max_gleanings: int = 1

    # Community reports.
    community_max_length: int = 2000
    community_max_input_length: int = 8000

    # Snapshots.
    export_graphml: bool = False

    # LLM request timeout in seconds (default 1800 = 30 min, suits large local models).
    request_timeout: int = 1800

    # Extra fields.
    language: Optional[str] = None


def _resolve_embedding(cfg: SettingsConfig) -> tuple[str, str, Optional[str], Optional[str]]:
    """Resolve embedding provider/model/base/key from the config."""
    provider = cfg.embedding_provider or cfg.llm_provider
    api_base = cfg.embedding_api_base or cfg.llm_api_base
    api_key = cfg.embedding_api_key or cfg.llm_api_key

    if cfg.embedding_model:
        model = cfg.embedding_model
    elif provider == "ollama":
        model = "nomic-embed-text"
    else:
        model = "text-embedding-3-small"

    return provider, model, api_base, api_key


def _ollama_api_base(cfg: SettingsConfig) -> str:
    """Return the Ollama API base URL."""
    return cfg.llm_api_base or "http://localhost:11434"


def generate_settings(
    target_dir: str | Path,
    *,
    config: Optional[SettingsConfig] = None,
    force: bool = False,
) -> Path:
    """Generate a ``settings.yaml`` file for a GraphRAG project.

    Parameters
    ----------
    target_dir:
        The GraphRAG project root directory.
    config:
        Settings configuration. Uses defaults if not provided.
    force:
        If ``True``, overwrite an existing ``settings.yaml``.

    Returns
    -------
    Path
        Path to the generated ``settings.yaml`` file.
    """
    cfg = config or SettingsConfig()
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    settings_path = target / "settings.yaml"
    if settings_path.exists() and not force:
        logger.info("settings: %s already exists — skipping (use force=True to overwrite)", settings_path)
        return settings_path

    emb_provider, emb_model, emb_base, emb_key = _resolve_embedding(cfg)

    yaml_content = _build_yaml(cfg, emb_provider, emb_model, emb_base, emb_key)
    settings_path.write_text(yaml_content, encoding="utf-8")

    # Also generate .env if API key is provided.
    env_path = target / ".env"
    env_lines: list[str] = []
    if cfg.llm_api_key:
        env_lines.append(f"GRAPHRAG_API_KEY={cfg.llm_api_key}")
    if emb_key and emb_key != cfg.llm_api_key:
        env_lines.append(f"GRAPHRAG_EMBEDDING_KEY={emb_key}")
    if env_lines and (not env_path.exists() or force):
        env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        logger.info("settings: wrote %s", env_path)

    logger.info("settings: generated %s", settings_path)
    return settings_path


def _build_yaml(
    cfg: SettingsConfig,
    emb_provider: str,
    emb_model: str,
    emb_base: Optional[str],
    emb_key: Optional[str],
) -> str:
    """Build the settings.yaml content string."""

    # --- Completion model ---
    if cfg.llm_provider == "ollama":
        api_base = _ollama_api_base(cfg)
        completion_block = (
            f"  default_completion_model:\n"
            f"    model_provider: ollama_chat\n"
            f"    model: {cfg.llm_model}\n"
            f"    api_base: {api_base}\n"
            f"    auth_method: api_key\n"
            f"    api_key: ollama\n"
            f"    call_args:\n"
            f"      timeout: {cfg.request_timeout}\n"
        )
    else:
        completion_block = (
            f"  default_completion_model:\n"
            f"    model_provider: {cfg.llm_provider}\n"
            f"    model: {cfg.llm_model}\n"
            f"    auth_method: api_key\n"
            f"    api_key: ${{GRAPHRAG_API_KEY}}\n"
            f"    call_args:\n"
            f"      timeout: {cfg.request_timeout}\n"
        )
        if cfg.llm_api_base:
            completion_block += f"    api_base: {cfg.llm_api_base}\n"

    # --- Embedding model ---
    if emb_provider == "ollama":
        emb_base_url = emb_base or _ollama_api_base(cfg)
        embedding_block = (
            f"  default_embedding_model:\n"
            f"    model_provider: ollama\n"
            f"    model: {emb_model}\n"
            f"    api_base: {emb_base_url}\n"
            f"    auth_method: api_key\n"
            f"    api_key: ollama\n"
            f"    call_args:\n"
            f"      timeout: {cfg.request_timeout}\n"
        )
    else:
        embedding_block = (
            f"  default_embedding_model:\n"
            f"    model_provider: {emb_provider}\n"
            f"    model: {emb_model}\n"
            f"    auth_method: api_key\n"
            f"    api_key: ${{GRAPHRAG_EMBEDDING_KEY}}\n"
            f"    call_args:\n"
            f"      timeout: {cfg.request_timeout}\n"
        )
        if emb_base:
            embedding_block += f"    api_base: {emb_base}\n"

    # --- Entity types ---
    entity_list = ", ".join(cfg.entity_types)

    # --- Assemble ---
    lines = [
        "# GraphRAG settings — generated by graphragloader",
        "",
        "completion_models:",
        completion_block.rstrip(),
        "",
        "embedding_models:",
        embedding_block.rstrip(),
        "",
        "input:",
        f"  type: {cfg.input_type}",
        f"  file_type: {cfg.input_type}",
        "  storage:",
        "    type: file",
        f"    base_dir: {cfg.input_dir}",
        "    encoding: utf-8",
        "",
        "output:",
        "  storage:",
        "    type: file",
        f"    base_dir: {cfg.output_dir}",
        "    encoding: utf-8",
        "",
        "cache:",
        "  type: json",
        "  storage:",
        "    type: file",
        "    base_dir: cache",
        "",
        "vector_store:",
        "  type: lancedb",
        f"  db_uri: {cfg.output_dir}/lancedb",
        "",
        "chunking:",
        "  type: tokens",
        f"  size: {cfg.chunk_size}",
        f"  overlap: {cfg.chunk_overlap}",
        "",
        "extract_graph:",
        f"  entity_types: [{entity_list}]",
        f"  max_gleanings: {cfg.max_gleanings}",
        "",
        "community_reports:",
        f"  max_length: {cfg.community_max_length}",
        f"  max_input_length: {cfg.community_max_input_length}",
        "",
        "snapshots:",
        f"  graphml: {str(cfg.export_graphml).lower()}",
        "",
    ]

    return "\n".join(lines) + "\n"
