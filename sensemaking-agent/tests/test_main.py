"""Tests for the CLI entrypoint and runtime configuration wiring."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

import sensemaking_agent.main as main_module
import sensemaking_agent.tools.scraper_tool as scraper_module
import sensemaking_agent.tools.search_tool as search_module
from sensemaking_agent.budget import BudgetTracker
from sensemaking_agent.config import LLMConfig


class _FakeWorkflow:
    def __init__(self, captured: dict[str, object]) -> None:
        self._captured = captured

    async def ainvoke(self, initial_state: dict[str, object]) -> dict[str, object]:
        self._captured["initial_state"] = initial_state
        self._captured["dry_run"] = search_module._dry_run
        self._captured["budget"] = search_module._budget
        self._captured["no_scrape"] = scraper_module._no_scrape
        self._captured["respect_robots"] = scraper_module._respect_robots
        return {"final_synthesis": "synthetic report"}


def test_build_arg_parser_accepts_runtime_controls() -> None:
    parser = main_module._build_arg_parser()

    args = parser.parse_args(
        [
            "--query",
            "grid storage",
            "--dry-run",
            "--tavily-key",
            "test-key",
            "--max-results",
            "7",
            "--max-queries",
            "4",
            "--max-credits",
            "12.5",
            "--warn-threshold",
            "0.9",
            "--no-scrape",
            "--no-respect-robots",
        ]
    )

    assert args.query == "grid storage"
    assert args.dry_run is True
    assert args.tavily_key == "test-key"
    assert args.max_results == 7
    assert args.max_queries == 4
    assert args.max_credits == 12.5
    assert args.warn_threshold == 0.9
    assert args.no_scrape is True
    assert args.respect_robots is False


@pytest.mark.asyncio
async def test_run_applies_runtime_controls_and_restores_globals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    fake_workflow = _FakeWorkflow(captured)

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    with patch("sensemaking_agent.main.build_workflow", return_value=fake_workflow) as build_workflow:
        result = await main_module.run(
            "grid storage",
            3,
            output_dir=None,
            dry_run=True,
            tavily_key="override-key",
            max_results=7,
            max_queries=4,
            max_credits=12.5,
            warn_threshold=0.9,
            no_scrape=True,
            respect_robots=False,
        )

    assert result == "synthetic report"
    assert captured["dry_run"] is True
    assert captured["no_scrape"] is True
    assert captured["respect_robots"] is False

    budget = captured["budget"]
    assert isinstance(budget, BudgetTracker)
    assert budget._max_queries == 4
    assert budget._max_credits == 12.5
    assert budget._warn_threshold == 0.9

    kwargs = build_workflow.call_args.kwargs
    scout_tool = kwargs["scout_tool"]
    assert scout_tool._search.max_results == 7
    assert kwargs["artifact_store"] is None
    assert kwargs["router_config"].max_iterations == 3
    assert isinstance(kwargs["llm_config"], LLMConfig)

    assert search_module._budget is None
    assert search_module._dry_run is False
    assert scraper_module._no_scrape is False
    assert scraper_module._respect_robots is True
    assert "TAVILY_API_KEY" not in os.environ


# ---------------------------------------------------------------------------
# _parse_requirements_file tests
# ---------------------------------------------------------------------------

class TestParseRequirementsFile:
    def test_section_based_parsing(self, tmp_path: Path) -> None:
        md = tmp_path / "requirements.md"
        md.write_text(
            "# Title\n\n"
            "## Topic\n\nHow to do X\n\n"
            "## Research Focus\n\nFocus on Y\n\n"
            "## Background\n\nContext about Z\n",
            encoding="utf-8",
        )
        query, prompt = main_module._parse_requirements_file(md)
        assert query == "How to do X"
        assert prompt is not None
        assert "Focus on Y" in prompt
        assert "Context about Z" in prompt

    def test_heading_fallback(self, tmp_path: Path) -> None:
        md = tmp_path / "topic.md"
        md.write_text("# My Great Topic\n\nSome details here.\n", encoding="utf-8")
        query, prompt = main_module._parse_requirements_file(md)
        assert query == "My Great Topic"
        assert prompt is not None
        assert "Some details here." in prompt

    def test_plain_text_fallback(self, tmp_path: Path) -> None:
        md = tmp_path / "topic.md"
        md.write_text("Just a plain query string", encoding="utf-8")
        query, prompt = main_module._parse_requirements_file(md)
        assert query == "Just a plain query string"
        assert prompt is None


# ---------------------------------------------------------------------------
# _parse_topic_dir tests
# ---------------------------------------------------------------------------

class TestParseTopicDir:
    def test_discovers_requirements_md(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.md").write_text(
            "## Topic\n\nMy research topic\n", encoding="utf-8"
        )
        query, prompt, prompt_dir, resources_dir = main_module._parse_topic_dir(tmp_path)
        assert query == "My research topic"
        assert prompt_dir is None
        assert resources_dir is None

    def test_discovers_prompts_and_resources(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.md").write_text("## Topic\n\nX\n", encoding="utf-8")
        (tmp_path / "prompts").mkdir()
        (tmp_path / "resources").mkdir()

        query, prompt, prompt_dir, resources_dir = main_module._parse_topic_dir(tmp_path)
        assert prompt_dir == str(tmp_path / "prompts")
        assert resources_dir == str(tmp_path / "resources")

    def test_falls_back_to_topic_md(self, tmp_path: Path) -> None:
        (tmp_path / "topic.md").write_text("# Fallback Topic\n\nDetails\n", encoding="utf-8")
        query, *_ = main_module._parse_topic_dir(tmp_path)
        assert query == "Fallback Topic"

    def test_falls_back_to_first_md(self, tmp_path: Path) -> None:
        # Create a.md (should be picked) and README.md (should be skipped)
        (tmp_path / "README.md").write_text("# Readme\n", encoding="utf-8")
        (tmp_path / "analysis.md").write_text("## Topic\n\nSome analysis\n", encoding="utf-8")
        query, *_ = main_module._parse_topic_dir(tmp_path)
        assert query == "Some analysis"

    def test_folder_name_fallback(self, tmp_path: Path) -> None:
        query, prompt, prompt_dir, resources_dir = main_module._parse_topic_dir(tmp_path)
        assert query == tmp_path.name
        assert prompt is None


# ---------------------------------------------------------------------------
# Arg parser: --topic-dir
# ---------------------------------------------------------------------------

class TestArgParserTopicDir:
    def test_topic_dir_accepted(self) -> None:
        parser = main_module._build_arg_parser()
        args = parser.parse_args(["--topic-dir", "/some/path"])
        assert args.topic_dir == "/some/path"
        assert args.query is None

    def test_query_and_topic_dir_mutually_exclusive(self) -> None:
        parser = main_module._build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--query", "test", "--topic-dir", "/path"])

    def test_neither_query_nor_topic_dir_fails(self) -> None:
        parser = main_module._build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--max-iterations", "3"])


# ---------------------------------------------------------------------------
# build_initial_state with pre-seeded docs and user_prompt
# ---------------------------------------------------------------------------

class TestBuildInitialStateExtensions:
    def test_pre_seeded_documents(self) -> None:
        from sensemaking_agent.state import build_initial_state

        docs = [{"document_id": "doc_1", "url": "file:///test.pdf", "content": "text"}]
        state = build_initial_state("test", documents=docs)
        assert len(state["documents"]) == 1
        assert state["documents"][0]["document_id"] == "doc_1"

    def test_user_prompt_set(self) -> None:
        from sensemaking_agent.state import build_initial_state

        state = build_initial_state("test", user_prompt="Extra context")
        assert state["user_prompt"] == "Extra context"

    def test_user_prompt_defaults_to_empty(self) -> None:
        from sensemaking_agent.state import build_initial_state

        state = build_initial_state("test")
        assert state["user_prompt"] == ""