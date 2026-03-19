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

        # Reset mock call count then call again
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
