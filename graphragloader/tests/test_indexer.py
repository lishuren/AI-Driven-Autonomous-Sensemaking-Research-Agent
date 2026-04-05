"""Tests for graphragloader.indexer — GraphRAG indexing wrapper."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graphragloader.indexer import (
    IndexResult,
    _compute_file_hashes,
    _load_state,
    _needs_reindex,
    _save_state,
    index,
)


class TestFileHashes:
    def test_empty_dir(self, tmp_path: Path) -> None:
        assert _compute_file_hashes(tmp_path) == {}

    def test_missing_dir(self, tmp_path: Path) -> None:
        assert _compute_file_hashes(tmp_path / "nope") == {}

    def test_computes_hashes(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("alpha")
        (tmp_path / "b.txt").write_text("beta")
        hashes = _compute_file_hashes(tmp_path)
        assert len(hashes) == 2
        assert all(len(v) == 64 for v in hashes.values())  # SHA-256 hex

    def test_deterministic(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("content")
        assert _compute_file_hashes(tmp_path) == _compute_file_hashes(tmp_path)

    def test_skips_hidden(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden").write_text("x")
        (tmp_path / "visible.txt").write_text("y")
        hashes = _compute_file_hashes(tmp_path)
        assert len(hashes) == 1


class TestState:
    def test_roundtrip(self, tmp_path: Path) -> None:
        state = {"file_hashes": {"a.txt": "abc123"}}
        _save_state(tmp_path, state)
        loaded = _load_state(tmp_path)
        assert loaded == state

    def test_load_missing(self, tmp_path: Path) -> None:
        assert _load_state(tmp_path) == {}

    def test_load_corrupt(self, tmp_path: Path) -> None:
        (tmp_path / ".graphragloader_state.json").write_text("not json")
        assert _load_state(tmp_path) == {}


class TestNeedsReindex:
    def test_fresh_needs_reindex(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("content")
        assert _needs_reindex(src, tmp_path / "target") is True

    def test_unchanged_no_reindex(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("content")

        target = tmp_path / "target"
        target.mkdir()
        hashes = _compute_file_hashes(src)
        _save_state(target, {"file_hashes": hashes})

        assert _needs_reindex(src, target) is False

    def test_changed_needs_reindex(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("content")

        target = tmp_path / "target"
        target.mkdir()
        _save_state(target, {"file_hashes": {"a.txt": "oldhash"}})

        assert _needs_reindex(src, target) is True


@pytest.mark.asyncio
class TestIndex:
    async def test_no_input_returns_error(self, tmp_path: Path) -> None:
        """Indexing with empty input/ should fail gracefully."""
        target = tmp_path / "target"
        target.mkdir()
        (target / "settings.yaml").write_text("completion_models: {}")

        result = await index(target)
        assert isinstance(result, IndexResult)
        assert result.success is False
        assert "No documents" in (result.error or "")

    async def test_converts_source_files(self, tmp_path: Path) -> None:
        """When source_dir is given, files should be converted first."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "doc.txt").write_text("test content")

        target = tmp_path / "target"

        with patch("graphragloader.indexer._run_index_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = IndexResult(success=True, target_dir=str(target))
            result = await index(target, source_dir=src, force=True)

        assert result.documents_converted == 1
        assert (target / "input").is_dir()

    async def test_skips_conversion_when_unchanged(self, tmp_path: Path) -> None:
        """Should skip conversion if file hashes match."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "doc.txt").write_text("content")

        target = tmp_path / "target"
        target.mkdir()
        input_dir = target / "input"
        input_dir.mkdir()
        (input_dir / "existing.txt").write_text("already there")
        (target / "settings.yaml").write_text("completion_models: {}")

        # Pre-save hashes.
        hashes = _compute_file_hashes(src)
        _save_state(target, {"file_hashes": hashes})

        with patch("graphragloader.indexer._run_index_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = IndexResult(success=True, target_dir=str(target))
            result = await index(target, source_dir=src)

        # conversion was skipped.
        assert result.documents_converted == 0

    async def test_falls_back_to_cli(self, tmp_path: Path) -> None:
        """When API import fails, should fall back to CLI."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "doc.txt").write_text("content")

        target = tmp_path / "target"

        with (
            patch("graphragloader.indexer._run_index_api", side_effect=ImportError("no graphrag")),
            patch("graphragloader.indexer._run_index_cli", new_callable=AsyncMock) as mock_cli,
        ):
            mock_cli.return_value = IndexResult(success=True, target_dir=str(target))
            result = await index(target, source_dir=src, force=True)

        assert result.success is True
        mock_cli.assert_called_once()
