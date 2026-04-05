"""Tests for the GraphRAG tool integration in sensemaking-agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from sensemaking_agent.tools.graphrag_tool import GraphRAGTool, _to_source_document


# ---------------------------------------------------------------------------
# _to_source_document
# ---------------------------------------------------------------------------

class TestToSourceDocument:
    def test_returns_dict_with_required_fields(self) -> None:
        result = MagicMock()
        result.method = "local"
        result.content = "Some content about X."
        result.metadata = {"community_level": 2}

        doc = _to_source_document(result, "what is X?")

        assert doc["document_id"].startswith("graphrag-")
        assert doc["source_type"] == "graphrag"
        assert doc["acquisition_method"] == "graphrag_local"
        assert "what is X?" in doc["title"]
        assert doc["content"] == "Some content about X."
        assert doc["query"] == "what is X?"

    def test_deterministic_id(self) -> None:
        result = MagicMock()
        result.method = "local"
        result.content = "A"
        result.metadata = {}

        a = _to_source_document(result, "q")
        b = _to_source_document(result, "q")
        assert a["document_id"] == b["document_id"]

    def test_global_method(self) -> None:
        result = MagicMock()
        result.method = "global"
        result.content = "Global view."
        result.metadata = {}

        doc = _to_source_document(result, "overview?")
        assert doc["acquisition_method"] == "graphrag_global"


# ---------------------------------------------------------------------------
# GraphRAGTool.query
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGraphRAGToolQuery:
    async def test_returns_empty_when_not_installed(self, tmp_path: Path) -> None:
        tool = GraphRAGTool(graphrag_dir=str(tmp_path))

        with patch("sensemaking_agent.tools.graphrag_tool._HAS_GRAPHRAGLOADER", False):
            result = await tool.query("test question")

        assert result == []

    async def test_returns_empty_for_missing_dir(self) -> None:
        tool = GraphRAGTool(graphrag_dir="/nonexistent/dir")

        with patch("sensemaking_agent.tools.graphrag_tool._HAS_GRAPHRAGLOADER", True):
            result = await tool.query("test question")

        assert result == []

    async def test_returns_document_on_success(self, tmp_path: Path) -> None:
        # Create a real directory so the existence check passes.
        graphrag_dir = tmp_path / "graphrag"
        graphrag_dir.mkdir()

        mock_result = MagicMock()
        mock_result.content = "Useful knowledge about topic."
        mock_result.method = "local"
        mock_result.metadata = {"community_level": 2}

        tool = GraphRAGTool(graphrag_dir=str(graphrag_dir))

        with (
            patch("sensemaking_agent.tools.graphrag_tool._HAS_GRAPHRAGLOADER", True),
            patch("sensemaking_agent.tools.graphrag_tool.graphrag_query", new_callable=AsyncMock, return_value=mock_result),
        ):
            result = await tool.query("what about topic?")

        assert len(result) == 1
        assert result[0]["source_type"] == "graphrag"
        assert "Useful knowledge" in result[0]["content"]

    async def test_returns_empty_on_error_result(self, tmp_path: Path) -> None:
        graphrag_dir = tmp_path / "graphrag"
        graphrag_dir.mkdir()

        mock_result = MagicMock()
        mock_result.content = "Error: no indexed data found."
        mock_result.method = "local"
        mock_result.metadata = {}

        tool = GraphRAGTool(graphrag_dir=str(graphrag_dir))

        with (
            patch("sensemaking_agent.tools.graphrag_tool._HAS_GRAPHRAGLOADER", True),
            patch("sensemaking_agent.tools.graphrag_tool.graphrag_query", new_callable=AsyncMock, return_value=mock_result),
        ):
            result = await tool.query("Q")

        assert result == []

    async def test_returns_empty_on_exception(self, tmp_path: Path) -> None:
        graphrag_dir = tmp_path / "graphrag"
        graphrag_dir.mkdir()

        tool = GraphRAGTool(graphrag_dir=str(graphrag_dir))

        with (
            patch("sensemaking_agent.tools.graphrag_tool._HAS_GRAPHRAGLOADER", True),
            patch("sensemaking_agent.tools.graphrag_tool.graphrag_query", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
        ):
            result = await tool.query("Q")

        assert result == []

    async def test_method_override(self, tmp_path: Path) -> None:
        graphrag_dir = tmp_path / "graphrag"
        graphrag_dir.mkdir()

        mock_result = MagicMock()
        mock_result.content = "Global answer."
        mock_result.method = "global"
        mock_result.metadata = {}

        tool = GraphRAGTool(graphrag_dir=str(graphrag_dir), method="local")

        with (
            patch("sensemaking_agent.tools.graphrag_tool._HAS_GRAPHRAGLOADER", True),
            patch("sensemaking_agent.tools.graphrag_tool.graphrag_query", new_callable=AsyncMock, return_value=mock_result) as mock_fn,
        ):
            await tool.query("Q", method="global")

        # Verify the override was passed through.
        call_kwargs = mock_fn.call_args
        assert call_kwargs.kwargs.get("method") == "global" or call_kwargs[1].get("method") == "global"
