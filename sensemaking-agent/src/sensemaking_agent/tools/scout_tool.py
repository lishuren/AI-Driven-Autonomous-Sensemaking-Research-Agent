"""Scout acquisition tool.

The Scout is the Body-layer entry point.  It accepts a query string,
runs a tiered content acquisition strategy, and returns a list of
normalised :class:`~sensemaking_agent.state.SourceDocument` records
ready to be merged into ``ResearchState``.

Acquisition tiers (in order, consistent with V1 proven approach):
  1. Tavily search — returns results with optional ``raw_content``.
  2. Tavily extract — for URLs that lacked sufficient raw_content.
  3. Playwright scrape — headless-browser fallback when extract fails.
  4. Search snippet — last resort when all above fail.

The Scout has no knowledge of entities, triplets, contradictions, or
routing.  Its only job is document acquisition and normalisation.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from ..state import SourceDocument
from .scraper_tool import ScraperTool
from .search_tool import SearchTool

logger = logging.getLogger(__name__)

# Minimum character threshold for raw_content to count as "sufficient".
_MIN_RAW_CONTENT_CHARS = 500


def _document_id(url: str, query: str) -> str:
    """Derive a stable, short document ID from a URL and the originating query."""
    digest = hashlib.sha1(f"{query}::{url}".encode()).hexdigest()[:16]
    return f"doc_{digest}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScoutTool:
    """Tiered document acquisition tool for the Scout node.

    Parameters
    ----------
    search_tool:
        Pre-configured :class:`~sensemaking_agent.tools.search_tool.SearchTool`.
    scraper_tool:
        Pre-configured :class:`~sensemaking_agent.tools.scraper_tool.ScraperTool`.
    """

    def __init__(
        self,
        search_tool: Optional[SearchTool] = None,
        scraper_tool: Optional[ScraperTool] = None,
    ) -> None:
        self._search = search_tool or SearchTool()
        self._scraper = scraper_tool or ScraperTool()

    async def acquire(self, query: str) -> list[SourceDocument]:
        """Run the full tiered acquisition pipeline for *query*.

        Returns a list of :class:`~sensemaking_agent.state.SourceDocument`
        Pydantic models.  The list may be empty if all acquisition tiers fail.
        """
        query = query.strip()
        if not query:
            logger.warning("ScoutTool.acquire called with an empty query.")
            return []

        logger.info("Scout acquiring documents for query: %r", query)

        # Tier 1: Tavily search.
        raw_results = await self._search.search(query)
        if not raw_results:
            logger.info("Scout: Tavily search returned no results for %r.", query)
            return []

        # Separate results that already have sufficient raw content from those
        # that need a second content acquisition pass.
        rich_results: list[dict[str, Any]] = []
        thin_urls: list[str] = []
        thin_results: list[dict[str, Any]] = []

        for result in raw_results:
            raw = result.get("raw_content", "")
            if raw and len(raw) >= _MIN_RAW_CONTENT_CHARS:
                rich_results.append(result)
            else:
                url = result.get("url", "")
                if url:
                    thin_urls.append(url)
                thin_results.append(result)

        # Tier 2: Tavily extract for URLs that lacked rich raw_content.
        extracted_by_url: dict[str, str] = {}
        if thin_urls:
            extract_results = await self._search.extract(thin_urls, query=query)
            for item in extract_results:
                url = item.get("url", "")
                content = item.get("content", "")
                if url and content:
                    extracted_by_url[url] = content

        documents: list[SourceDocument] = []

        # Produce documents for rich results directly.
        for result in rich_results:
            doc = self._build_document(
                result=result,
                content=result["raw_content"],
                query=query,
                method="tavily_raw_content",
            )
            if doc is not None:
                documents.append(doc)

        # Produce documents for thin results, falling back through extract → scrape → snippet.
        for result in thin_results:
            url = result.get("url", "")
            content: Optional[str] = None
            method = "tavily_snippet"

            # Tier 2 result available?
            if url and url in extracted_by_url:
                content = extracted_by_url[url]
                method = "tavily_extract"
            else:
                # Tier 3: Playwright scrape.
                if url:
                    scraped = await self._scraper.scrape(url)
                    if scraped:
                        content = scraped
                        method = "playwright"

            # Tier 4: fall back to the search snippet.
            if not content:
                content = result.get("body", "").strip()
                method = "tavily_snippet"

            if not content:
                logger.debug("Scout: no content for URL %r — skipping.", url[:80])
                continue

            doc = self._build_document(
                result=result,
                content=content,
                query=query,
                method=method,
            )
            if doc is not None:
                documents.append(doc)

        logger.info(
            "Scout acquired %d documents for query %r.", len(documents), query
        )
        return documents

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_document(
        self,
        result: dict[str, Any],
        content: str,
        query: str,
        method: str,
    ) -> Optional[SourceDocument]:
        """Build and validate a :class:`SourceDocument` from a raw result dict.

        Returns ``None`` when required fields are missing or Pydantic validation
        fails.
        """
        url = (result.get("url") or "").strip()
        title = (result.get("title") or "").strip()

        if not url:
            logger.debug("Scout: skipping result with no URL (title=%r).", title[:60])
            return None

        try:
            return SourceDocument(
                document_id=_document_id(url, query),
                url=url,
                title=title or url,
                content=content,
                source_type="web",
                query=query,
                retrieved_at=datetime.now(timezone.utc),
                acquisition_method=method,
                metadata={},
            )
        except Exception as exc:
            logger.warning("Scout: failed to build SourceDocument for %r: %s", url[:80], exc)
            return None
