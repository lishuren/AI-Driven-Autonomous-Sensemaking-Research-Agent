"""Per-session budget tracker for Tavily API credit usage.

Adapted from the V1 BudgetTracker pattern — V2 version tracks
queries and credits only (no topic-graph node budget, since V2
has no topic-graph node concept).
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BudgetTracker:
    """In-memory per-session budget tracker.

    Parameters
    ----------
    max_queries:
        Maximum search+extract API calls allowed.  ``None`` = unlimited.
    max_credits:
        Maximum Tavily API credits to spend.  ``None`` = unlimited.
    warn_threshold:
        Fraction of any limit at which a one-time WARNING is logged.
        Default is ``0.80`` (80 %).  Pass ``1.0`` to disable warnings.
    """

    def __init__(
        self,
        max_queries: Optional[int] = None,
        max_credits: Optional[float] = None,
        warn_threshold: float = 0.80,
    ) -> None:
        self._max_queries = max_queries
        self._max_credits = max_credits
        self._warn_threshold = warn_threshold

        self._queries_used: int = 0
        self._credits_used: float = 0.0
        self._limit_warning_logged: bool = False

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_query(self, credits: float = 1.0) -> None:
        """Increment the query counter and add *credits* to the running total.

        Also emits a one-time WARNING when any budget threshold is crossed.
        """
        self._queries_used += 1
        self._credits_used += credits

        if not self._limit_warning_logged and self.approaching_limit():
            logger.warning(
                "Budget usage at %.0f%%: %d queries used (limit=%s), "
                "%.1f credits used (limit=%s).",
                self.used_fraction() * 100,
                self._queries_used,
                str(self._max_queries) if self._max_queries is not None else "∞",
                self._credits_used,
                str(self._max_credits) if self._max_credits is not None else "∞",
            )
            self._limit_warning_logged = True

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def can_query(self) -> bool:
        """Return ``True`` when the query is permitted under current limits."""
        if self._max_queries is not None and self._queries_used >= self._max_queries:
            return False
        if self._max_credits is not None and self._credits_used >= self._max_credits:
            return False
        return True

    def is_exhausted(self) -> bool:
        """Return ``True`` when any configured limit has been reached."""
        return not self.can_query()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def used_fraction(self) -> float:
        """Return the highest fraction of any configured limit consumed (0.0–1.0).

        Returns ``0.0`` when no limits are configured.
        """
        fractions: list[float] = []
        if self._max_queries is not None and self._max_queries > 0:
            fractions.append(self._queries_used / self._max_queries)
        if self._max_credits is not None and self._max_credits > 0:
            fractions.append(self._credits_used / self._max_credits)
        return max(fractions, default=0.0)

    def approaching_limit(self) -> bool:
        """Return ``True`` when any limit is configured and usage is at or above
        the warn threshold.  A ``warn_threshold`` of ``1.0`` disables warnings."""
        if self._warn_threshold >= 1.0:
            return False
        limits_configured = self._max_queries is not None or self._max_credits is not None
        return limits_configured and self.used_fraction() >= self._warn_threshold

    def summary(self) -> str:
        """Return a human-readable one-line budget summary."""
        q_limit = str(self._max_queries) if self._max_queries is not None else "∞"
        c_limit = (
            f"{self._max_credits:.1f}" if self._max_credits is not None else "∞"
        )
        return (
            f"queries={self._queries_used}/{q_limit}, "
            f"credits={self._credits_used:.1f}/{c_limit}, "
            f"warn_threshold={self._warn_threshold:.0%}"
        )

    @property
    def queries_used(self) -> int:
        return self._queries_used

    @property
    def credits_used(self) -> float:
        return self._credits_used
