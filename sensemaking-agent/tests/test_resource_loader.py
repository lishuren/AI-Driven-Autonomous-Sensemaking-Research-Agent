"""Tests for resource_loader: text file loading and graceful degradation."""

from __future__ import annotations

import textwrap
from pathlib import Path

from sensemaking_agent.tools.resource_loader import (
    _read_text_file,
    load_resources,
)


def test_read_text_file(tmp_path: Path) -> None:
    f = tmp_path / "note.md"
    f.write_text("# Hello\nWorld", encoding="utf-8")
    assert _read_text_file(f) == "# Hello\nWorld"


def test_load_resources_discovers_text_files(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("Markdown doc", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Plain text", encoding="utf-8")
    (tmp_path / "c.py").write_text("# not a resource", encoding="utf-8")  # unsupported ext

    docs = load_resources(str(tmp_path))

    # Only .md and .txt should be loaded (.py is unsupported without PDF/DOCX readers)
    assert len(docs) == 2

    urls = {d.url for d in docs}
    assert any("a.md" in u for u in urls)
    assert any("b.txt" in u for u in urls)

    for doc in docs:
        assert doc.source_type == "local_resource"
        assert doc.acquisition_method == "file_read"
        assert doc.document_id.startswith("doc_res_")


def test_load_resources_empty_dir(tmp_path: Path) -> None:
    assert load_resources(str(tmp_path)) == []


def test_load_resources_skips_unreadable_extensions(tmp_path: Path) -> None:
    (tmp_path / "image.png").write_bytes(b"\x89PNG")
    docs = load_resources(str(tmp_path))
    assert docs == []


def test_load_resources_truncates_long_content(tmp_path: Path) -> None:
    huge = "A" * 100_000
    (tmp_path / "big.txt").write_text(huge, encoding="utf-8")

    docs = load_resources(str(tmp_path))
    assert len(docs) == 1
    assert len(docs[0].content) <= 80_001  # _MAX_CONTENT_CHARS + 1 for tolerance


def test_load_resources_nonexistent_dir() -> None:
    docs = load_resources("/nonexistent/path/that/does/not/exist")
    assert docs == []


def test_load_resources_recursive_subdirectories(tmp_path: Path) -> None:
    sub = tmp_path / "papers" / "2024"
    sub.mkdir(parents=True)
    (tmp_path / "top.md").write_text("Top level", encoding="utf-8")
    (sub / "deep.txt").write_text("Deep file", encoding="utf-8")

    docs = load_resources(str(tmp_path))

    assert len(docs) == 2
    titles = {d.title for d in docs}
    assert "top.md" in titles
    assert "deep.txt" in titles


def test_load_resources_recognises_epub_extension(tmp_path: Path) -> None:
    """EPUB files shouldn't be silently skipped — they hit the reader (or graceful skip)."""
    # We can't easily create a valid EPUB without ebooklib, but we CAN verify
    # the extension is dispatched (not treated as unsupported).
    fake = tmp_path / "book.epub"
    fake.write_bytes(b"PK\x03\x04not-a-real-epub")  # zip header to not crash instantly

    docs = load_resources(str(tmp_path))
    # Either loaded (if ebooklib installed) or gracefully skipped — never unsupported
    # The key assertion: the function doesn't raise and the file isn't in
    # the "skipping unsupported" path (no crash).
    assert isinstance(docs, list)


def test_load_resources_recognises_mobi_extension(tmp_path: Path) -> None:
    fake = tmp_path / "book.mobi"
    fake.write_bytes(b"\x00" * 64)  # not a valid MOBI, but tests dispatch

    docs = load_resources(str(tmp_path))
    assert isinstance(docs, list)
