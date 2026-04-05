"""Tests for the Scout acquisition layer.

All external I/O (Tavily HTTP, Playwright) is replaced with async fakes so
the tests run offline without any API keys or browsers installed.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import pytest

import sensemaking_agent.tools.search_tool as search_module
from sensemaking_agent.budget import BudgetTracker
from sensemaking_agent.nodes.scout_node import make_scout_node
from sensemaking_agent.state import SourceDocument
from sensemaking_agent.tools.scout_tool import ScoutTool
from sensemaking_agent.tools.search_tool import SearchTool, set_budget, set_dry_run
from sensemaking_agent.tools.scraper_tool import ScraperTool, set_no_scrape


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_search_result(
    url: str = "https://example.com/article",
    title: str = "Example Article",
    body: str = "Short snippet.",
    raw_content: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {"url": url, "title": title, "body": body}
    if raw_content:
        result["raw_content"] = raw_content
    return result


def _rich_result(url: str = "https://example.com/rich") -> dict[str, Any]:
    return _make_search_result(url=url, raw_content="A" * 600)


def _thin_result(url: str = "https://example.com/thin") -> dict[str, Any]:
    return _make_search_result(url=url, body="Short snippet for thin result.")


# ---------------------------------------------------------------------------
# SearchTool — dry-run mode
# ---------------------------------------------------------------------------

class TestSearchToolDryRun:
    def setup_method(self) -> None:
        set_dry_run(False)  # ensure clean state before each test

    def teardown_method(self) -> None:
        set_dry_run(False)

    @pytest.mark.asyncio
    async def test_dry_run_returns_empty_list(self) -> None:
        set_dry_run(True)
        tool = SearchTool()
        results = await tool.search("test query")
        assert results == []

    @pytest.mark.asyncio
    async def test_dry_run_extract_returns_empty_list(self) -> None:
        set_dry_run(True)
        tool = SearchTool()
        results = await tool.extract(["https://example.com"])
        assert results == []


# ---------------------------------------------------------------------------
# SearchTool — budget exhaustion guard
# ---------------------------------------------------------------------------

class TestSearchToolBudget:
    def setup_method(self) -> None:
        set_dry_run(False)

    @pytest.mark.asyncio
    async def test_search_respects_exhausted_budget(self) -> None:
        tracker = BudgetTracker(max_queries=0)
        set_budget(tracker)
        tool = SearchTool()
        results = await tool.search("test query")
        assert results == []
        # Reset global
        search_module._budget = None

    @pytest.mark.asyncio
    async def test_extract_respects_exhausted_budget(self) -> None:
        tracker = BudgetTracker(max_queries=0)
        set_budget(tracker)
        tool = SearchTool()
        results = await tool.extract(["https://example.com"])
        assert results == []
        search_module._budget = None


# ---------------------------------------------------------------------------
# SearchTool — missing API key
# ---------------------------------------------------------------------------

class TestSearchToolMissingKey:
    def setup_method(self) -> None:
        set_dry_run(False)
        search_module._budget = None

    @pytest.mark.asyncio
    async def test_search_returns_empty_when_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        tool = SearchTool()
        results = await tool.search("test query")
        assert results == []

    @pytest.mark.asyncio
    async def test_extract_returns_empty_when_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        tool = SearchTool()
        results = await tool.extract(["https://example.com"])
        assert results == []


# ---------------------------------------------------------------------------
# ScoutTool — document normalization
# ---------------------------------------------------------------------------

class TestScoutToolAcquire:
    def setup_method(self) -> None:
        set_dry_run(False)
        search_module._budget = None

    @pytest.mark.asyncio
    async def test_acquire_returns_empty_for_blank_query(self) -> None:
        scout = ScoutTool()
        docs = await scout.acquire("   ")
        assert docs == []

    @pytest.mark.asyncio
    async def test_acquire_returns_empty_when_search_returns_nothing(self) -> None:
        mock_search = AsyncMock(return_value=[])
        scout = ScoutTool(search_tool=SearchTool())
        scout._search.search = mock_search
        docs = await scout.acquire("some query")
        assert docs == []

    @pytest.mark.asyncio
    async def test_acquire_uses_raw_content_for_rich_results(self) -> None:
        rich = _rich_result()
        mock_search = AsyncMock(return_value=[rich])
        mock_extract = AsyncMock(return_value=[])

        search_tool = SearchTool()
        search_tool.search = mock_search
        search_tool.extract = mock_extract

        scout = ScoutTool(search_tool=search_tool)
        docs = await scout.acquire("test query")

        assert len(docs) == 1
        doc = docs[0]
        assert doc.acquisition_method == "tavily_raw_content"
        assert doc.content == "A" * 600
        assert doc.url == rich["url"]
        assert doc.query == "test query"
        # extract should not have been called for a rich result
        mock_extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_acquire_falls_back_to_extract_for_thin_results(self) -> None:
        thin = _thin_result()
        extracted_content = "Full extracted content from Tavily Extract."
        mock_search = AsyncMock(return_value=[thin])
        mock_extract = AsyncMock(
            return_value=[{"url": thin["url"], "content": extracted_content}]
        )

        search_tool = SearchTool()
        search_tool.search = mock_search
        search_tool.extract = mock_extract

        scout = ScoutTool(search_tool=search_tool)
        docs = await scout.acquire("test query")

        assert len(docs) == 1
        doc = docs[0]
        assert doc.acquisition_method == "tavily_extract"
        assert doc.content == extracted_content

    @pytest.mark.asyncio
    async def test_acquire_falls_back_to_playwright(self) -> None:
        thin = _thin_result()
        scraped_content = "Content from Playwright headless browser."

        mock_search = AsyncMock(return_value=[thin])
        mock_extract = AsyncMock(return_value=[])  # extract returns nothing

        scraper = ScraperTool()
        scraper.scrape = AsyncMock(return_value=scraped_content)  # type: ignore[method-assign]

        search_tool = SearchTool()
        search_tool.search = mock_search
        search_tool.extract = mock_extract

        scout = ScoutTool(search_tool=search_tool, scraper_tool=scraper)
        docs = await scout.acquire("test query")

        assert len(docs) == 1
        assert docs[0].acquisition_method == "playwright"
        assert docs[0].content == scraped_content

    @pytest.mark.asyncio
    async def test_acquire_falls_back_to_snippet(self) -> None:
        thin = _thin_result()
        mock_search = AsyncMock(return_value=[thin])
        mock_extract = AsyncMock(return_value=[])

        scraper = ScraperTool()
        scraper.scrape = AsyncMock(return_value=None)  # type: ignore[method-assign]

        search_tool = SearchTool()
        search_tool.search = mock_search
        search_tool.extract = mock_extract

        scout = ScoutTool(search_tool=search_tool, scraper_tool=scraper)
        docs = await scout.acquire("test query")

        assert len(docs) == 1
        assert docs[0].acquisition_method == "tavily_snippet"
        assert docs[0].content == thin["body"]

    @pytest.mark.asyncio
    async def test_acquire_skips_result_with_no_url_and_no_content(self) -> None:
        no_url_result: dict[str, Any] = {"url": "", "title": "No URL", "body": ""}
        mock_search = AsyncMock(return_value=[no_url_result])
        mock_extract = AsyncMock(return_value=[])

        scraper = ScraperTool()
        scraper.scrape = AsyncMock(return_value=None)  # type: ignore[method-assign]

        search_tool = SearchTool()
        search_tool.search = mock_search
        search_tool.extract = mock_extract

        scout = ScoutTool(search_tool=search_tool, scraper_tool=scraper)
        docs = await scout.acquire("test query")
        assert docs == []

    @pytest.mark.asyncio
    async def test_acquire_returns_source_document_instances(self) -> None:
        rich = _rich_result()
        mock_search = AsyncMock(return_value=[rich])
        mock_extract = AsyncMock(return_value=[])

        search_tool = SearchTool()
        search_tool.search = mock_search
        search_tool.extract = mock_extract

        scout = ScoutTool(search_tool=search_tool)
        docs = await scout.acquire("query")

        assert all(isinstance(doc, SourceDocument) for doc in docs)

    @pytest.mark.asyncio
    async def test_document_id_is_deterministic(self) -> None:
        rich = _rich_result()
        mock_search = AsyncMock(return_value=[rich])
        mock_extract = AsyncMock(return_value=[])

        search_tool = SearchTool()
        search_tool.search = mock_search
        search_tool.extract = mock_extract

        scout = ScoutTool(search_tool=search_tool)
        docs_first = await scout.acquire("stable query")

        mock_search.return_value = [rich]
        docs_second = await scout.acquire("stable query")

        assert docs_first[0].document_id == docs_second[0].document_id

    @pytest.mark.asyncio
    async def test_mixed_results_use_correct_tier(self) -> None:
        rich = _rich_result(url="https://example.com/rich")
        thin = _thin_result(url="https://example.com/thin")

        extracted = "Extracted content for thin URL."
        mock_search = AsyncMock(return_value=[rich, thin])
        mock_extract = AsyncMock(
            return_value=[{"url": thin["url"], "content": extracted}]
        )

        search_tool = SearchTool()
        search_tool.search = mock_search
        search_tool.extract = mock_extract

        scout = ScoutTool(search_tool=search_tool)
        docs = await scout.acquire("mixed query")

        assert len(docs) == 2
        methods = {doc.url: doc.acquisition_method for doc in docs}
        assert methods[rich["url"]] == "tavily_raw_content"
        assert methods[thin["url"]] == "tavily_extract"


class TestScoutNode:
    @pytest.mark.asyncio
    async def test_scout_node_augments_query_with_entities_and_constraints(self) -> None:
        scout_tool = AsyncMock()
        scout_tool.acquire = AsyncMock(return_value=[])
        node = make_scout_node(scout_tool)

        state = {
            "current_query": "legacy .NET maintenance",
            "iteration_count": 0,
            "constraints": "Avoid upgrade guidance",
            "documents": [
                {
                    "document_id": "doc_local_1",
                    "url": "file:///tmp/notes.md",
                    "title": "notes.md",
                    "content": "content",
                    "source_type": "local_resource",
                    "query": "",
                    "acquisition_method": "file_read",
                    "metadata": {"original_path": "C:/tmp/notes.md"},
                }
            ],
            "entities": {
                "NDepend": {
                    "canonical_name": "NDepend",
                    "aliases": [],
                    "evidence_refs": [],
                    "source_document_ids": ["doc_local_1"],
                }
            },
        }

        await node(state)

        effective_query = scout_tool.acquire.await_args.args[0]
        assert "legacy .NET maintenance" in effective_query
        assert "NDepend" in effective_query
        assert "Avoid upgrade guidance" in effective_query

    @pytest.mark.asyncio
    async def test_scout_node_polls_new_resource_files_when_watch_enabled(self, tmp_path) -> None:
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()
        new_file = resource_dir / "notes.md"
        new_file.write_text("hello", encoding="utf-8")

        watched_doc = SourceDocument(
            document_id="doc_local_1",
            url=new_file.resolve().as_uri(),
            title="notes.md",
            content="hello",
            source_type="local_resource",
            query="",
            acquisition_method="file_read",
            metadata={"original_path": str(new_file.resolve())},
        )

        scout_tool = AsyncMock()
        scout_tool.acquire = AsyncMock(return_value=[])
        node = make_scout_node(scout_tool)

        state = {
            "current_query": "legacy .NET maintenance",
            "iteration_count": 0,
            "documents": [],
            "entities": {},
            "watched_resources_dir": str(resource_dir),
            "watched_resources_seen": [],
        }

        with patch("sensemaking_agent.nodes.scout_node.load_resources", return_value=[watched_doc]):
            result = await node(state)

        assert len(result["documents"]) == 1
        assert result["documents"][0]["document_id"] == "doc_local_1"
        assert len(result["watched_resources_seen"]) == 1


# ---------------------------------------------------------------------------
# ScraperTool — no_scrape flag
# ---------------------------------------------------------------------------

class TestScraperToolNoScrape:
    def setup_method(self) -> None:
        set_no_scrape(False)

    def teardown_method(self) -> None:
        set_no_scrape(False)

    @pytest.mark.asyncio
    async def test_scrape_returns_none_when_disabled(self) -> None:
        set_no_scrape(True)
        tool = ScraperTool()
        result = await tool.scrape("https://example.com")
        assert result is None
