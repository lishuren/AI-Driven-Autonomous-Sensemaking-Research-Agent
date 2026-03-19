"""Tests for BudgetTracker."""

from __future__ import annotations

import pytest

from sensemaking_agent.budget import BudgetTracker


# ---------------------------------------------------------------------------
# Basic accounting
# ---------------------------------------------------------------------------

def test_initial_state_is_zero() -> None:
    tracker = BudgetTracker()
    assert tracker.queries_used == 0
    assert tracker.credits_used == 0.0


def test_record_query_increments_counters() -> None:
    tracker = BudgetTracker()
    tracker.record_query(credits=2.5)
    assert tracker.queries_used == 1
    assert tracker.credits_used == 2.5


def test_multiple_records_accumulate() -> None:
    tracker = BudgetTracker()
    tracker.record_query(credits=1.0)
    tracker.record_query(credits=3.0)
    assert tracker.queries_used == 2
    assert tracker.credits_used == 4.0


# ---------------------------------------------------------------------------
# Limit guards
# ---------------------------------------------------------------------------

def test_can_query_without_limits() -> None:
    tracker = BudgetTracker()
    assert tracker.can_query() is True


def test_can_query_blocked_after_query_limit() -> None:
    tracker = BudgetTracker(max_queries=2)
    tracker.record_query()
    tracker.record_query()
    assert tracker.can_query() is False


def test_can_query_blocked_after_credit_limit() -> None:
    tracker = BudgetTracker(max_credits=5.0)
    tracker.record_query(credits=5.0)
    assert tracker.can_query() is False


def test_is_exhausted_mirrors_can_query() -> None:
    tracker = BudgetTracker(max_queries=1)
    assert tracker.is_exhausted() is False
    tracker.record_query()
    assert tracker.is_exhausted() is True


# ---------------------------------------------------------------------------
# Fractional usage
# ---------------------------------------------------------------------------

def test_used_fraction_zero_with_no_limits() -> None:
    tracker = BudgetTracker()
    tracker.record_query(credits=100.0)
    assert tracker.used_fraction() == 0.0


def test_used_fraction_with_query_limit() -> None:
    tracker = BudgetTracker(max_queries=4)
    tracker.record_query()
    tracker.record_query()
    assert tracker.used_fraction() == pytest.approx(0.5)


def test_used_fraction_with_credit_limit() -> None:
    tracker = BudgetTracker(max_credits=10.0)
    tracker.record_query(credits=7.5)
    assert tracker.used_fraction() == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Threshold warnings
# ---------------------------------------------------------------------------

def test_approaching_limit_false_before_threshold() -> None:
    tracker = BudgetTracker(max_queries=10, warn_threshold=0.80)
    for _ in range(7):
        tracker.record_query()
    assert tracker.approaching_limit() is False


def test_approaching_limit_true_at_threshold() -> None:
    tracker = BudgetTracker(max_queries=10, warn_threshold=0.80)
    for _ in range(8):
        tracker.record_query()
    assert tracker.approaching_limit() is True


def test_approaching_limit_false_without_limits() -> None:
    tracker = BudgetTracker(warn_threshold=0.80)
    for _ in range(100):
        tracker.record_query(credits=100.0)
    assert tracker.approaching_limit() is False


def test_warning_threshold_100_never_warns() -> None:
    tracker = BudgetTracker(max_queries=2, warn_threshold=1.0)
    tracker.record_query()
    tracker.record_query()
    assert tracker.approaching_limit() is False


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def test_summary_unlimited() -> None:
    tracker = BudgetTracker()
    summary = tracker.summary()
    assert "∞" in summary
    assert "queries=0" in summary


def test_summary_with_limits() -> None:
    tracker = BudgetTracker(max_queries=10, max_credits=50.0)
    tracker.record_query(credits=3.0)
    summary = tracker.summary()
    assert "queries=1/10" in summary
    assert "credits=3.0/50.0" in summary
