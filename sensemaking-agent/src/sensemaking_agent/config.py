"""Runtime configuration for the sensemaking agent.

Settings are resolved in priority order:
  1. Explicit constructor argument
  2. Environment variable
  3. Documented default value

All settings are plain dataclass fields so they are easy to override
in tests without patching environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _int_env(name: str) -> Optional[int]:
    val = os.environ.get(name, "").strip()
    if val:
        try:
            return int(val)
        except ValueError:
            pass
    return None


def _float_env(name: str) -> Optional[float]:
    val = os.environ.get(name, "").strip()
    if val:
        try:
            return float(val)
        except ValueError:
            pass
    return None


def _bool_env(name: str, default: bool) -> bool:
    val = os.environ.get(name, "").strip().lower()
    if val in ("1", "true", "yes"):
        return True
    if val in ("0", "false", "no"):
        return False
    return default


@dataclass
class SearchConfig:
    """Configuration for the Tavily search and extract layer."""

    # Tavily API key — set via TAVILY_API_KEY in the environment.
    tavily_api_key: str = field(
        default_factory=lambda: os.environ.get("TAVILY_API_KEY", "").strip()
    )

    # Maximum results per search call.
    max_results: int = 5

    # Minimum seconds between consecutive Tavily search calls.
    rate_limit_min: float = 2.0

    # Maximum seconds between consecutive Tavily search calls.
    rate_limit_max: float = 5.0

    # Seconds before a search HTTP request times out.
    search_timeout: int = 15

    # Seconds before an extract HTTP request times out.
    extract_timeout: int = 20


@dataclass
class ScraperConfig:
    """Configuration for the Playwright fallback scraper."""

    # Whether to skip Playwright scraping entirely.
    no_scrape: bool = field(
        default_factory=lambda: _bool_env("SENSEMAKING_NO_SCRAPE", False)
    )

    # Whether to apply the advisory robots.txt check before scraping.
    respect_robots: bool = field(
        default_factory=lambda: _bool_env("SENSEMAKING_RESPECT_ROBOTS", True)
    )

    # Wait at most this many milliseconds for a page to load.
    page_timeout_ms: int = 15_000

    # Truncate page content to this many characters.
    max_content_chars: int = 20_000

    # Number of retry attempts for transient scrape errors.
    retry_max_attempts: int = 3

    # Base backoff seconds between retries (doubles each attempt).
    retry_backoff_base: float = 1.0


@dataclass
class BudgetConfig:
    """Budget limits for search API usage."""

    # Maximum number of Tavily search or extract API calls.
    max_queries: Optional[int] = field(
        default_factory=lambda: _int_env("SENSEMAKING_MAX_QUERIES")
    )

    # Maximum Tavily API credits to spend.
    max_credits: Optional[float] = field(
        default_factory=lambda: _float_env("SENSEMAKING_MAX_CREDITS")
    )

    # Fraction of any limit at which a warning is logged.
    warn_threshold: float = 0.80


@dataclass
class LLMConfig:
    """Configuration for the LLM used by Analyst, Critic, and Writer nodes."""

    # Ollama model name (or OpenAI-compatible model identifier).
    model: str = field(
        default_factory=lambda: os.environ.get(
            "SENSEMAKING_LLM_MODEL", "qwen2.5:7b"
        ).strip()
    )

    # Base URL for the LLM server.
    base_url: str = field(
        default_factory=lambda: os.environ.get(
            "SENSEMAKING_LLM_BASE_URL", "http://localhost:11434"
        ).strip()
    )

    # Provider: "ollama" or "openai" (and OpenAI-compatible aliases).
    provider: str = field(
        default_factory=lambda: os.environ.get(
            "SENSEMAKING_LLM_PROVIDER", "ollama"
        ).strip()
    )

    # API key — required for OpenAI-compatible providers, empty for Ollama.
    api_key: str = field(
        default_factory=lambda: os.environ.get("SENSEMAKING_LLM_API_KEY", "").strip()
    )

    # Seconds before an LLM call times out.
    timeout: int = 120

    # Truncate document content to this many characters before sending to LLM.
    max_content_chars: int = 8_000


@dataclass
class AgentConfig:
    """Top-level agent configuration bundle."""

    search: SearchConfig = field(default_factory=SearchConfig)
    scraper: ScraperConfig = field(default_factory=ScraperConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
