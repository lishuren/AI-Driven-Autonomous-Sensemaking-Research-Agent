"""Playwright-based fallback scraper for the Scout acquisition layer.

Fetches a URL using a headless Chromium browser when Tavily search or
extract did not return sufficient content.  Implements retry with
exponential backoff, robots.txt advisory checks, and user-agent rotation.

Playwright is an optional dependency.  When not installed the module
degrades gracefully: ``ScraperTool.scrape()`` always returns ``None``
and logs a one-time warning.
"""

from __future__ import annotations

import asyncio
import logging
import random
import urllib.parse
import urllib.robotparser
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional Playwright import
# ---------------------------------------------------------------------------

try:
    from playwright.async_api import async_playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False
    logger.debug(
        "playwright not installed — Playwright scraping will be unavailable. "
        "Install it with: pip install playwright && playwright install chromium"
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PAGE_TIMEOUT_MS = 15_000
_MAX_CONTENT_CHARS = 20_000
_RETRY_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_BASE = 1.0  # seconds

_SCRAPE_DELAY_MIN = 0.5  # seconds — random delay before each scrape
_SCRAPE_DELAY_MAX = 2.0

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
]

# Error substrings that indicate a transient network failure worth retrying.
_TRANSIENT_KEYWORDS = (
    "timeout",
    "timed out",
    "connection reset",
    "connection refused",
    "dns",
    "network",
    "eof occurred",
    "broken pipe",
    "temporarily unavailable",
    "429",
    "503",
)

# Error substrings that indicate a permanent failure — do not retry.
_PERMANENT_KEYWORDS = (
    "404",
    "403",
    "401",
    "invalid url",
    "net::err_name_not_resolved",
    "net::err_aborted",
)

# ---------------------------------------------------------------------------
# Module-level flags — set once at startup via helpers
# ---------------------------------------------------------------------------

_no_scrape: bool = False
_respect_robots: bool = True
_robots_cache: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}


def set_no_scrape(enabled: bool) -> None:
    """When *enabled*, :meth:`ScraperTool.scrape` always returns ``None``."""
    global _no_scrape
    _no_scrape = enabled


def set_respect_robots(enabled: bool) -> None:
    """Enable or disable the advisory robots.txt check before scraping."""
    global _respect_robots
    _respect_robots = enabled


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_robots_txt(url: str) -> bool:
    """Return ``True`` if scraping is permitted by robots.txt (advisory only).

    Returns ``True`` on any fetch error so robots.txt unavailability never
    silently blocks acquisition.
    """
    if not _respect_robots:
        return True

    parsed = urllib.parse.urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    if domain not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{domain}/robots.txt")
        try:
            rp.read()
            _robots_cache[domain] = rp
        except Exception:
            _robots_cache[domain] = None

    cached = _robots_cache.get(domain)
    if cached is None:
        return True

    allowed = cached.can_fetch("*", url)
    if not allowed:
        logger.info("robots.txt advisory: %r disallowed (proceeding anyway).", url[:80])
    return allowed


def _is_transient_error(exc: Exception) -> bool:
    """Return ``True`` for transient errors that are worth retrying."""
    text = str(exc).lower()
    if any(kw in text for kw in _PERMANENT_KEYWORDS):
        return False
    if any(kw in text for kw in _TRANSIENT_KEYWORDS):
        return True
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


# ---------------------------------------------------------------------------
# Public scraper
# ---------------------------------------------------------------------------

class ScraperTool:
    """Playwright-backed scraper that renders JavaScript before extracting text.

    This is a Scout-layer dependency only.  It does not touch orchestration
    state, contradictions, or graph structures.
    """

    async def scrape(self, url: str) -> Optional[str]:
        """Fetch *url*, render JavaScript, and return plain-text body content.

        Returns ``None`` when:
        - ``no_scrape`` flag is set
        - Playwright is not installed
        - all retry attempts are exhausted
        - a permanent HTTP error is encountered
        """
        if _no_scrape:
            logger.debug("Scraping is disabled — skipping %r.", url[:80])
            return None

        if not _HAS_PLAYWRIGHT:
            logger.warning(
                "playwright is not installed — cannot scrape %r. "
                "Run: pip install playwright && playwright install chromium",
                url[:80],
            )
            return None

        _check_robots_txt(url)

        ua = random.choice(_USER_AGENTS)

        for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
            try:
                await asyncio.sleep(random.uniform(_SCRAPE_DELAY_MIN, _SCRAPE_DELAY_MAX))

                async with async_playwright() as pw:
                    browser = await pw.chromium.launch(headless=True)
                    try:
                        context = await browser.new_context(user_agent=ua)
                        page = await context.new_page()
                        await page.goto(
                            url,
                            timeout=_PAGE_TIMEOUT_MS,
                            wait_until="domcontentloaded",
                        )
                        content = await page.inner_text("body")
                    finally:
                        await browser.close()

                lines = [line.strip() for line in content.splitlines() if line.strip()]
                text = "\n".join(lines)[:_MAX_CONTENT_CHARS]
                if text:
                    logger.info("Scraped %d chars from %r.", len(text), url[:80])
                    return text
                return None

            except Exception as exc:
                transient = _is_transient_error(exc)
                if not transient or attempt >= _RETRY_MAX_ATTEMPTS:
                    logger.warning(
                        "Scrape failed for %r (attempt %d/%d, %s): %s",
                        url[:80],
                        attempt,
                        _RETRY_MAX_ATTEMPTS,
                        "transient" if transient else "permanent",
                        exc,
                    )
                    break

                backoff = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                jitter = random.uniform(0.0, 0.1 * backoff)
                logger.info(
                    "Transient scrape error for %r (attempt %d/%d), retrying in %.1fs: %s",
                    url[:80],
                    attempt,
                    _RETRY_MAX_ATTEMPTS,
                    backoff + jitter,
                    exc,
                )
                await asyncio.sleep(backoff + jitter)

        logger.warning(
            "Scrape exhausted all %d attempts for %r.", _RETRY_MAX_ATTEMPTS, url[:80]
        )
        return None
