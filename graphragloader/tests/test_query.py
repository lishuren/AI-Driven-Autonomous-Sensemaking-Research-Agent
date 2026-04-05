"""Tests for graphragloader.query — async GraphRAG query wrapper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graphragloader.query import (
    QueryResult,
    _find_output_dir,
    _load_parquet,
    query,
)


class TestFindOutputDir:
    def test_default_output_subdir(self, tmp_path: Path) -> None:
        out = tmp_path / "output"
        out.mkdir()
        assert _find_output_dir(tmp_path) == out

    def test_fallback_to_target(self, tmp_path: Path) -> None:
        (tmp_path / "entities.parquet").write_text("fake")
        assert _find_output_dir(tmp_path) == tmp_path

    def test_returns_default_when_nothing(self, tmp_path: Path) -> None:
        result = _find_output_dir(tmp_path)
        assert result == tmp_path / "output"


class TestLoadParquet:
    def test_missing_returns_empty_df(self, tmp_path: Path) -> None:
        df = _load_parquet(tmp_path / "nope.parquet")
        assert len(df) == 0


@pytest.mark.asyncio
class TestQuery:
    async def test_config_load_failure(self, tmp_path: Path) -> None:
        """If config cannot be loaded, should return error result."""
        with patch("graphrag.config.load_config.load_config", side_effect=Exception("bad config")):
            result = await query(tmp_path, "test question")

        assert isinstance(result, QueryResult)
        assert "Error" in result.content

    async def test_no_entities_returns_error(self, tmp_path: Path) -> None:
        """If no indexed data, should return a helpful error."""
        import pandas as pd

        mock_config = MagicMock()
        empty_tables = {
            "entities": pd.DataFrame(),
            "communities": pd.DataFrame(),
            "community_reports": pd.DataFrame(),
            "text_units": pd.DataFrame(),
            "relationships": pd.DataFrame(),
            "covariates": pd.DataFrame(),
        }

        with (
            patch("graphrag.config.load_config.load_config", return_value=mock_config),
            patch("graphragloader.query._load_output_tables", return_value=empty_tables),
        ):
            result = await query(tmp_path, "test question")

        assert "no indexed data" in result.content.lower() or "Error" in result.content

    async def test_unknown_method(self, tmp_path: Path) -> None:
        """Unknown search method should return error."""
        import pandas as pd

        mock_config = MagicMock()
        tables = {
            "entities": pd.DataFrame({"id": [1]}),
            "communities": pd.DataFrame(),
            "community_reports": pd.DataFrame(),
            "text_units": pd.DataFrame(),
            "relationships": pd.DataFrame(),
            "covariates": pd.DataFrame(),
        }

        with (
            patch("graphrag.config.load_config.load_config", return_value=mock_config),
            patch("graphragloader.query._load_output_tables", return_value=tables),
        ):
            result = await query(tmp_path, "test", method="nonexistent")

        assert "unknown" in result.content.lower()

    async def test_local_search_dispatch(self, tmp_path: Path) -> None:
        """Local search should dispatch to _query_local."""
        import pandas as pd

        mock_config = MagicMock()
        tables = {
            "entities": pd.DataFrame({"id": [1]}),
            "communities": pd.DataFrame(),
            "community_reports": pd.DataFrame(),
            "text_units": pd.DataFrame(),
            "relationships": pd.DataFrame(),
            "covariates": pd.DataFrame(),
        }

        expected = QueryResult(content="found it", method="local")

        with (
            patch("graphrag.config.load_config.load_config", return_value=mock_config),
            patch("graphragloader.query._load_output_tables", return_value=tables),
            patch("graphragloader.query._query_local", new_callable=AsyncMock, return_value=expected) as mock_local,
        ):
            result = await query(tmp_path, "what is X?", method="local")

        assert result.content == "found it"
        mock_local.assert_called_once()

    async def test_global_search_dispatch(self, tmp_path: Path) -> None:
        """Global search should dispatch to _query_global."""
        import pandas as pd

        mock_config = MagicMock()
        tables = {
            "entities": pd.DataFrame({"id": [1]}),
            "communities": pd.DataFrame(),
            "community_reports": pd.DataFrame(),
            "text_units": pd.DataFrame(),
            "relationships": pd.DataFrame(),
            "covariates": pd.DataFrame(),
        }

        expected = QueryResult(content="global answer", method="global")

        with (
            patch("graphrag.config.load_config.load_config", return_value=mock_config),
            patch("graphragloader.query._load_output_tables", return_value=tables),
            patch("graphragloader.query._query_global", new_callable=AsyncMock, return_value=expected),
        ):
            result = await query(tmp_path, "big picture?", method="global")

        assert result.content == "global answer"
        assert result.method == "global"
