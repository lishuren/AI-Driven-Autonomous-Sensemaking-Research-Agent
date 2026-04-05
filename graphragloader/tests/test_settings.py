"""Tests for graphragloader.settings — settings.yaml generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphragloader.settings import SettingsConfig, generate_settings


class TestSettingsConfig:
    """Dataclass defaults."""

    def test_defaults(self) -> None:
        cfg = SettingsConfig()
        assert cfg.llm_provider == "ollama"
        assert cfg.llm_model == "qwen2.5:7b"
        assert cfg.chunk_size == 1200
        assert "organization" in cfg.entity_types


class TestGenerateSettings:
    """settings.yaml file generation."""

    def test_creates_settings_yaml(self, tmp_path: Path) -> None:
        path = generate_settings(tmp_path)
        assert path == tmp_path / "settings.yaml"
        assert path.exists()

    def test_ollama_config(self, tmp_path: Path) -> None:
        generate_settings(tmp_path, config=SettingsConfig(llm_provider="ollama"))
        content = (tmp_path / "settings.yaml").read_text(encoding="utf-8")
        assert "ollama_chat" in content
        assert "ollama_embedding" in content
        assert "nomic-embed-text" in content

    def test_openai_config(self, tmp_path: Path) -> None:
        cfg = SettingsConfig(
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            llm_api_key="sk-test",
        )
        generate_settings(tmp_path, config=cfg, force=True)
        content = (tmp_path / "settings.yaml").read_text(encoding="utf-8")
        assert "gpt-4o-mini" in content
        assert "GRAPHRAG_API_KEY" in content

    def test_creates_env_with_api_key(self, tmp_path: Path) -> None:
        cfg = SettingsConfig(llm_api_key="sk-secret")
        generate_settings(tmp_path, config=cfg)
        env = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "sk-secret" in env

    def test_does_not_overwrite_by_default(self, tmp_path: Path) -> None:
        generate_settings(tmp_path)
        original = (tmp_path / "settings.yaml").read_text(encoding="utf-8")

        # Second call with different model should not overwrite.
        cfg2 = SettingsConfig(llm_model="different-model")
        generate_settings(tmp_path, config=cfg2)
        assert (tmp_path / "settings.yaml").read_text(encoding="utf-8") == original

    def test_force_overwrites(self, tmp_path: Path) -> None:
        generate_settings(tmp_path)
        cfg2 = SettingsConfig(llm_model="different-model")
        generate_settings(tmp_path, config=cfg2, force=True)
        content = (tmp_path / "settings.yaml").read_text(encoding="utf-8")
        assert "different-model" in content

    def test_creates_target_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        generate_settings(nested)
        assert (nested / "settings.yaml").exists()

    def test_yaml_structure(self, tmp_path: Path) -> None:
        generate_settings(tmp_path)
        content = (tmp_path / "settings.yaml").read_text(encoding="utf-8")
        for section in ("completion_models:", "embedding_models:", "input:", "output:", "chunking:", "extract_graph:"):
            assert section in content

    def test_custom_embedding(self, tmp_path: Path) -> None:
        cfg = SettingsConfig(
            embedding_provider="openai",
            embedding_model="text-embedding-3-large",
            embedding_api_key="emb-key",
        )
        generate_settings(tmp_path, config=cfg)
        content = (tmp_path / "settings.yaml").read_text(encoding="utf-8")
        assert "text-embedding-3-large" in content
