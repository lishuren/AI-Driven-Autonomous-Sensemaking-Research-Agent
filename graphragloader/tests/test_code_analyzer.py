"""Tests for graphragloader.code_analyzer — source code structural extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphragloader.code_analyzer import (
    analyze_code,
    analyze_code_files,
    _analyze_python,
    _analyze_plain,
)


class TestAnalyzePython:
    """AST-based Python analysis."""

    def test_extracts_function(self) -> None:
        source = 'def greet(name: str) -> str:\n    """Say hello."""\n    return f"Hello {name}"\n'
        result = _analyze_python(source, Path("greet.py"))
        assert "greet" in result
        assert "Say hello" in result

    def test_extracts_class(self) -> None:
        source = (
            "class Dog:\n"
            '    """A dog."""\n'
            "    def bark(self):\n"
            "        pass\n"
        )
        result = _analyze_python(source, Path("dog.py"))
        assert "class Dog" in result
        assert "bark" in result

    def test_extracts_imports(self) -> None:
        source = "import os\nfrom pathlib import Path\n"
        result = _analyze_python(source, Path("imp.py"))
        assert "os" in result
        assert "pathlib.Path" in result

    def test_handles_syntax_error(self) -> None:
        source = "def broken(\n"
        result = _analyze_python(source, Path("bad.py"))
        assert "syntax error" in result.lower()
        assert "def broken(" in result  # raw content preserved

    def test_extracts_decorators(self) -> None:
        source = "@staticmethod\ndef helper():\n    pass\n"
        result = _analyze_python(source, Path("dec.py"))
        assert "staticmethod" in result

    def test_module_docstring(self) -> None:
        source = '"""Top-level module doc."""\n\nx = 1\n'
        result = _analyze_python(source, Path("mod.py"))
        assert "Top-level module doc" in result


class TestAnalyzePlain:
    """Fallback plain text wrapping."""

    def test_wraps_in_code_block(self) -> None:
        result = _analyze_plain("console.log('hi');", Path("app.js"))
        assert "```js" in result
        assert "console.log" in result

    def test_includes_filename(self) -> None:
        result = _analyze_plain("fn main() {}", Path("main.rs"))
        assert "main.rs" in result


class TestAnalyzeCodeFiles:
    """Single-file public API."""

    def test_python_file(self, tmp_path: Path) -> None:
        p = tmp_path / "example.py"
        p.write_text("def add(a, b):\n    return a + b\n")
        result = analyze_code_files(p)
        assert result is not None
        assert "add" in result

    def test_unknown_extension_fallback(self, tmp_path: Path) -> None:
        p = tmp_path / "script.lua"
        p.write_text("print('hello')\n")
        result = analyze_code_files(p)
        assert result is not None
        assert "hello" in result

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.py"
        p.write_text("")
        assert analyze_code_files(p) is None

    def test_missing_file(self, tmp_path: Path) -> None:
        assert analyze_code_files(tmp_path / "nope.py") is None


class TestAnalyzeCode:
    """Directory-level code analysis."""

    def test_analyzes_directory(self, tmp_path: Path) -> None:
        src = tmp_path / "project"
        src.mkdir()
        (src / "main.py").write_text("def main():\n    pass\n")
        (src / "utils.py").write_text("def helper():\n    pass\n")

        target = tmp_path / "out"
        results = analyze_code(src, target)

        assert len(results) == 2
        titles = {r.title for r in results}
        assert "main.py" in titles
        assert "utils.py" in titles

        # Output files in target/input/.
        output_files = list((target / "input").glob("*.txt"))
        assert len(output_files) == 2

    def test_skips_pycache(self, tmp_path: Path) -> None:
        src = tmp_path / "project"
        src.mkdir()
        cache = src / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-312.pyc").write_text("bytecode")
        (src / "real.py").write_text("x = 1\n")

        target = tmp_path / "out"
        results = analyze_code(src, target)
        assert len(results) == 1
        assert results[0].title == "real.py"

    def test_empty_source_dir(self, tmp_path: Path) -> None:
        src = tmp_path / "empty"
        src.mkdir()
        results = analyze_code(src, tmp_path / "out")
        assert results == []

    def test_missing_source_dir(self, tmp_path: Path) -> None:
        results = analyze_code(tmp_path / "nope", tmp_path / "out")
        assert results == []

    def test_result_metadata(self, tmp_path: Path) -> None:
        src = tmp_path / "project"
        src.mkdir()
        (src / "app.py").write_text("x = 42\n")

        target = tmp_path / "out"
        results = analyze_code(src, target)

        assert len(results) == 1
        doc = results[0]
        assert doc.format == "code"
        assert doc.metadata.get("language") == "py"
        assert "size_bytes" in doc.metadata
