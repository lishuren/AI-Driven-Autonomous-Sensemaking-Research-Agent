"""Tests for graphragloader.cli — command-line interface."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graphragloader.cli import _build_parser, main


class TestParser:
    """Argument parsing tests."""

    def test_convert_args(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["convert", "--source", "/src", "--target", "/tgt"])
        assert args.command == "convert"
        assert args.source == "/src"
        assert args.target == "/tgt"
        assert args.include_code is False

    def test_convert_with_code(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["convert", "--source", "/s", "--target", "/t", "--include-code"])
        assert args.include_code is True

    def test_index_args(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["index", "--source", "/s", "--target", "/t"])
        assert args.command == "index"
        assert args.method == "standard"
        assert args.force is False

    def test_index_with_options(self) -> None:
        parser = _build_parser()
        args = parser.parse_args([
            "index", "--source", "/s", "--target", "/t",
            "--method", "fast", "--force",
            "--provider", "openai", "--model", "gpt-4o",
        ])
        assert args.method == "fast"
        assert args.force is True
        assert args.provider == "openai"
        assert args.model == "gpt-4o"

    def test_query_args(self) -> None:
        parser = _build_parser()
        args = parser.parse_args([
            "query", "--target", "/t", "--question", "what is X?"
        ])
        assert args.command == "query"
        assert args.question == "what is X?"
        assert args.method == "local"

    def test_init_args(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["init", "--target", "/t"])
        assert args.command == "init"
        assert args.provider == "ollama"

    def test_no_command(self) -> None:
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.command is None


class TestMain:
    def test_no_command_returns_1(self) -> None:
        assert main([]) == 1

    def test_convert(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("content")

        result = main(["convert", "--source", str(src), "--target", str(tmp_path / "out")])
        assert result == 0

    def test_init(self, tmp_path: Path) -> None:
        target = tmp_path / "project"
        result = main(["init", "--target", str(target)])
        assert result == 0
        assert (target / "settings.yaml").exists()

    def test_init_force(self, tmp_path: Path) -> None:
        target = tmp_path / "project"
        main(["init", "--target", str(target)])
        result = main(["init", "--target", str(target), "--force"])
        assert result == 0
