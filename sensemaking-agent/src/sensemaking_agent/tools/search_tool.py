"""Tavily search and extract wrapper for the Scout acquisition layer.

Provides a thin, testable async interface around the Tavily Search and
Extract APIs.  The module keeps V1-proven patterns (rate limiting, credit
tracking, dry-run mode, CJK language detection) while staying decoupled
from any orchestration state.

No graph logic, contradiction logic, or entity extraction belongs here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from ..budget import BudgetTracker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"
_TAVILY_EXTRACT_ENDPOINT = "https://api.tavily.com/extract"
_TAVILY_USAGE_ENDPOINT = "https://api.tavily.com/usage"

_SEARCH_TIMEOUT = 15   # seconds
_EXTRACT_TIMEOUT = 20  # seconds
_DEFAULT_MAX_RESULTS = 5

_RATE_LIMIT_MIN = 2.0  # seconds between consecutive search calls
_RATE_LIMIT_MAX = 5.0

# Unicode CJK ranges for language detection.
_CJK_RANGES = (
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
    (0x20000, 0x2A6DF),
    (0xAC00, 0xD7AF),
    (0x3040, 0x30FF),
)

# ---------------------------------------------------------------------------
# Module-level state (set via helpers before first search call)
# ---------------------------------------------------------------------------

_budget: Optional[BudgetTracker] = None
_dry_run: bool = False
_tavily_quota_exhausted: bool = False


def set_budget(tracker: BudgetTracker) -> None:
    """Attach a :class:`BudgetTracker` so every API call records credit usage."""
    global _budget
    _budget = tracker


def set_dry_run(enabled: bool = True) -> None:
    """Enable or disable dry-run mode.

    When enabled, all search/extract calls return empty results without
    making any HTTP requests.  Useful for cost estimation.
    """
    global _dry_run
    _dry_run = enabled


# ---------------------------------------------------------------------------
# Language detection (CJK-aware)
# ---------------------------------------------------------------------------

def _detect_language(text: str) -> str:
    """Return ``"zh"`` when >30% of characters are CJK/Hangul/Kana, else ``"en"``."""
    if not text:
        return "en"
    cjk_count = sum(
        1 for ch in text
        if any(lo <= ord(ch) <= hi for lo, hi in _CJK_RANGES)
    )
    return "zh" if cjk_count / len(text) > 0.30 else "en"


# ---------------------------------------------------------------------------
# Internal synchronous Tavily calls (run in executor)
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    return os.environ.get("TAVILY_API_KEY", "").strip()


def _tavily_search_sync(
    query: str,
    max_results: int,
    api_key: str,
) -> list[dict[str, Any]]:
    """Execute a Tavily Search API call and return normalised results.

    Returns ``[]`` when the API key is missing, quota is exhausted, or
    any network error occurs.
    """
    global _tavily_quota_exhausted
    if _tavily_quota_exhausted or not api_key:
        return []

    body: dict[str, Any] = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": False,
        "include_usage": True,
        "include_raw_content": "markdown",
    }
    if _detect_language(query) == "zh":
        body["country"] = "china"

    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        _TAVILY_SEARCH_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_SEARCH_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 429, 432):
            _tavily_quota_exhausted = True
            logger.warning(
                "Tavily search quota exhausted (HTTP %d) — disabled for this run.",
                exc.code,
            )
        else:
            logger.warning("Tavily search HTTP error for %r: %s", query, exc)
        return []
    except Exception as exc:
        logger.warning("Tavily search error for %r: %s", query, exc)
        return []

    usage = data.get("usage", {})
    credits = float(usage.get("credits", 1))
    if _budget is not None:
        _budget.record_query(credits=credits)

    results: list[dict[str, Any]] = []
    for item in data.get("results", []):
        entry: dict[str, Any] = {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "body": item.get("content", ""),
        }
        raw = item.get("raw_content") or ""
        if raw:
            entry["raw_content"] = raw
        results.append(entry)

    logger.info("Tavily search returned %d results for %r.", len(results), query)
    return results


def _tavily_extract_sync(
    urls: list[str],
    query: str,
    api_key: str,
) -> list[dict[str, Any]]:
    """Execute a Tavily Extract API call for up to 20 URLs.

    Returns a list of ``{'url': str, 'content': str}`` dicts.
    """
    global _tavily_quota_exhausted
    if _tavily_quota_exhausted or not api_key or not urls:
        return []

    body: dict[str, Any] = {
        "api_key": api_key,
        "urls": urls[:20],
        "include_usage": True,
        "extract_depth": "basic",
        "format": "markdown",
    }
    if query:
        body["query"] = query

    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        _TAVILY_EXTRACT_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_EXTRACT_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 429, 432):
            _tavily_quota_exhausted = True
            logger.warning("Tavily extract quota exhausted (HTTP %d).", exc.code)
        else:
            logger.warning("Tavily extract HTTP error: %s", exc)
        return []
    except Exception as exc:
        logger.warning("Tavily extract error: %s", exc)
        return []

    usage = data.get("usage", {})
    credits = float(usage.get("credits", len(urls) / 5.0))
    if _budget is not None:
        _budget.record_query(credits=credits)

    results: list[dict[str, Any]] = []
    for item in data.get("results", []):
        content = item.get("raw_content") or item.get("content") or ""
        url = item.get("url", "")
        if content and url:
            results.append({"url": url, "content": content})

    logger.info(
        "Tavily Extract returned content for %d / %d URLs.",
        len(results),
        len(urls),
    )
    return results


def _fetch_account_credits_sync() -> Optional[dict[str, Any]]:
    """Fetch current account credit usage from Tavily /usage endpoint.

    Returns a normalised dict or ``None`` on any error.  Best-effort only.
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    req = urllib.request.Request(
        f"{_TAVILY_USAGE_ENDPOINT}?api_key={urllib.parse.quote(api_key)}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        result: dict[str, Any] = {}
        for src_key, dst_key in (
            ("used", "credits_used"),
            ("credits_used", "credits_used"),
            ("limit", "credits_limit"),
            ("credits_limit", "credits_limit"),
            ("remaining", "credits_remaining"),
            ("credits_remaining", "credits_remaining"),
        ):
            if src_key in data and dst_key not in result:
                result[dst_key] = data[src_key]
        return result if result else data
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 405, 501):
            logger.debug("Tavily /usage not available (HTTP %d).", exc.code)
        else:
            logger.debug("Tavily /usage HTTP error: %s", exc)
        return None
    except Exception as exc:
        logger.debug("Tavily /usage fetch failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

class SearchTool:
    """Async-friendly Tavily Search + Extract wrapper.

    Designed to be the sole search and extract backend for the Scout layer.
    Does not perform any graph mutations or contradiction analysis.
    """

    def __init__(self, max_results: int = _DEFAULT_MAX_RESULTS) -> None:
        self.max_results = max_results
        self._last_call: float = 0.0

    async def search(self, query: str) -> list[dict[str, Any]]:
        """Search Tavily for *query* and return normalised result dicts.

        Each result has keys ``title``, ``url``, ``body``, and optionally
        ``raw_content`` when Tavily returned fuller page text.

        Returns ``[]`` when dry-run mode is active, when budget is exhausted,
        or on any network failure.
        """
        if _dry_run:
            logger.debug("Dry-run: skipping search for %r.", query)
            return []

        if _budget is not None and not _budget.can_query():
            logger.info("Budget exhausted — skipping search for %r.", query)
            return []

        # Rate limiting: enforce minimum gap between consecutive calls.
        elapsed = time.monotonic() - self._last_call
        wait = random.uniform(_RATE_LIMIT_MIN, _RATE_LIMIT_MAX)
        if elapsed < wait:
            await asyncio.sleep(wait - elapsed)

        api_key = _get_api_key()
        if not api_key:
            logger.warning(
                "TAVILY_API_KEY is not set — search for %r will return no results.",
                query,
            )
            return []

        loop = asyncio.get_event_loop()
        try:
            results = await loop.run_in_executor(
                None, _tavily_search_sync, query, self.max_results, api_key
            )
        except Exception as exc:
            logger.warning("Search executor error for %r: %s", query, exc)
            results = []

        self._last_call = time.monotonic()
        return results

    async def extract(self, urls: list[str], query: str = "") -> list[dict[str, Any]]:
        """Extract full content for *urls* via Tavily Extract API.

        Returns a list of ``{'url': str, 'content': str}`` dicts.
        Skips the call when dry-run mode is active or the budget is exhausted.
        """
        if _dry_run:
            logger.debug("Dry-run: skipping extract for %d URLs.", len(urls))
            return []

        if _budget is not None and not _budget.can_query():
            logger.info("Budget exhausted — skipping extract.")
            return []

        api_key = _get_api_key()
        if not api_key:
            logger.warning("TAVILY_API_KEY is not set — extract will return no results.")
            return []

        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None, _tavily_extract_sync, urls, query, api_key
            )
        except Exception as exc:
            logger.warning("Extract executor error: %s", exc)
            return []

    async def fetch_account_credits(self) -> Optional[dict[str, Any]]:
        """Return current Tavily account credit usage or ``None`` if unavailable."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch_account_credits_sync)
