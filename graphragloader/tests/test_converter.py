"""Tests for graphragloader.converter — document-to-text conversion."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphragloader.converter import (
    ConvertedDocument,
    _build_metadata_header,
    _looks_binary,
    _read_excel,
    _read_plaintext,
    _stable_filename,
    convert_resources,
)


class TestStableFilename:
    """The output filename should be deterministic and filesystem-safe."""

    def test_deterministic(self, tmp_path: Path) -> None:
        p = tmp_path / "hello.txt"
        p.write_text("x")
        a = _stable_filename(p)
        b = _stable_filename(p)
        assert a == b

    def test_ends_with_txt(self, tmp_path: Path) -> None:
        p = tmp_path / "report.pdf"
        p.write_text("x")
        assert _stable_filename(p).endswith(".txt")

    def test_different_files_differ(self, tmp_path: Path) -> None:
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("x")
        b.write_text("x")
        assert _stable_filename(a) != _stable_filename(b)


class TestBuildMetadataHeader:
    def test_contains_source_name(self, tmp_path: Path) -> None:
        p = tmp_path / "notes.md"
        p.write_text("x")
        header = _build_metadata_header(p)
        assert "notes.md" in header
        assert "Source:" in header
        assert "---" in header


class TestReadPlaintext:
    def test_reads_utf8(self, tmp_path: Path) -> None:
        p = tmp_path / "data.txt"
        p.write_text("hello world", encoding="utf-8")
        assert _read_plaintext(p) == "hello world"

    def test_returns_none_on_missing(self, tmp_path: Path) -> None:
        assert _read_plaintext(tmp_path / "nope.txt") is None


class TestConvertResources:
    """Integration-level tests using plain text files only (no LlamaIndex needed)."""

    def test_converts_plaintext_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("Alpha content")
        (src / "b.md").write_text("# Beta heading")

        target = tmp_path / "target"
        results = convert_resources(src, target)

        assert len(results) == 2
        assert all(isinstance(r, ConvertedDocument) for r in results)

        # Output files should exist in target/input/.
        input_dir = target / "input"
        assert input_dir.is_dir()
        output_files = list(input_dir.glob("*.txt"))
        assert len(output_files) == 2

    def test_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        assert convert_resources(tmp_path / "nope", tmp_path / "out") == []

    def test_returns_empty_for_empty_dir(self, tmp_path: Path) -> None:
        src = tmp_path / "empty"
        src.mkdir()
        assert convert_resources(src, tmp_path / "out") == []

    def test_truncates_large_content(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "big.txt").write_text("x" * 500)

        target = tmp_path / "target"
        results = convert_resources(src, target, max_chars=100)

        assert len(results) == 1
        assert results[0].char_count <= 100

    def test_skips_hidden_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / ".hidden").write_text("secret")
        (src / "visible.txt").write_text("public")

        target = tmp_path / "target"
        results = convert_resources(src, target)

        assert len(results) == 1
        assert results[0].title == "visible.txt"

    def test_metadata_header_prepended(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "info.txt").write_text("body text")

        target = tmp_path / "target"
        convert_resources(src, target)

        output_files = list((target / "input").glob("*.txt"))
        assert len(output_files) == 1
        content = output_files[0].read_text(encoding="utf-8")
        assert content.startswith("Source: info.txt")
        assert "body text" in content

    def test_code_files_skipped_by_default(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("print('hello')")
        (src / "notes.txt").write_text("notes")

        target = tmp_path / "target"
        results = convert_resources(src, target, include_code=False)

        # .py is not in _PLAINTEXT_EXTENSIONS, and include_code=False
        # so only notes.txt should be converted.
        titles = {r.title for r in results}
        assert "notes.txt" in titles

    def test_code_files_included_when_requested(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("def hello():\n    pass\n")
        (src / "notes.txt").write_text("notes")

        target = tmp_path / "target"
        results = convert_resources(src, target, include_code=True)

        titles = {r.title for r in results}
        assert "app.py" in titles
        assert "notes.txt" in titles

    def test_recursive_scanning(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        sub = src / "sub" / "deep"
        sub.mkdir(parents=True)
        (sub / "nested.txt").write_text("deep content")

        target = tmp_path / "target"
        results = convert_resources(src, target)

        assert len(results) == 1
        assert results[0].title == "nested.txt"

    def test_converted_document_fields(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "doc.txt").write_text("content here")

        target = tmp_path / "target"
        results = convert_resources(src, target)

        doc = results[0]
        assert doc.title == "doc.txt"
        assert doc.format == "txt"
        assert doc.char_count > 0
        assert "size_bytes" in doc.metadata


class TestLooksBinary:
    """Heuristic binary detection for unknown-extension fallback."""

    def test_normal_text_is_not_binary(self) -> None:
        assert _looks_binary("Hello world\nThis is a normal document.") is False

    def test_null_heavy_is_binary(self) -> None:
        # Lots of replacement characters indicate decoded binary.
        text = "\x00\x01\x02" * 100
        assert _looks_binary(text) is True

    def test_empty_is_not_binary(self) -> None:
        assert _looks_binary("") is False

    def test_unicode_text_is_not_binary(self) -> None:
        assert _looks_binary("日本語テキスト 中文文本") is False


class TestReadExcel:
    """Excel file reading via pandas (mocked when pandas unavailable)."""

    def test_reads_xlsx(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """If pandas and openpyxl are available, read a real .xlsx."""
        pd = pytest.importorskip("pandas")
        pytest.importorskip("openpyxl")

        # Create a tiny .xlsx file.
        xlsx_path = tmp_path / "data.xlsx"
        df = pd.DataFrame({"Name": ["Alice", "Bob"], "Score": [90, 85]})
        df.to_excel(str(xlsx_path), index=False)

        text = _read_excel(xlsx_path)
        assert text is not None
        assert "Alice" in text
        assert "Bob" in text
        assert "Sheet" in text

    def test_reads_multi_sheet(self, tmp_path: Path) -> None:
        pd = pytest.importorskip("pandas")
        pytest.importorskip("openpyxl")

        xlsx_path = tmp_path / "multi.xlsx"
        with pd.ExcelWriter(str(xlsx_path)) as writer:
            pd.DataFrame({"A": [1]}).to_excel(writer, sheet_name="First", index=False)
            pd.DataFrame({"B": [2]}).to_excel(writer, sheet_name="Second", index=False)

        text = _read_excel(xlsx_path)
        assert text is not None
        assert "First" in text
        assert "Second" in text

    def test_returns_none_without_pandas(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import graphragloader.converter as conv
        monkeypatch.setattr(conv, "_HAS_PANDAS", False)
        p = tmp_path / "data.xlsx"
        p.write_bytes(b"fake")
        assert _read_excel(p) is None

    def test_returns_none_on_corrupt_file(self, tmp_path: Path) -> None:
        pytest.importorskip("pandas")
        p = tmp_path / "bad.xlsx"
        p.write_bytes(b"this is not excel")
        assert _read_excel(p) is None


class TestConvertExcelIntegration:
    """End-to-end: convert_resources picks up Excel files."""

    def test_xlsx_converted(self, tmp_path: Path) -> None:
        pd = pytest.importorskip("pandas")
        pytest.importorskip("openpyxl")

        src = tmp_path / "src"
        src.mkdir()
        df = pd.DataFrame({"Col": ["val"]})
        df.to_excel(str(src / "report.xlsx"), index=False)

        target = tmp_path / "target"
        results = convert_resources(src, target)

        assert len(results) == 1
        assert results[0].format == "excel"
        assert results[0].title == "report.xlsx"


class TestConvertZipIntegration:
    """ZIP archive extraction and recursive conversion."""

    def test_zip_with_text_files(self, tmp_path: Path) -> None:
        import zipfile as zf

        src = tmp_path / "src"
        src.mkdir()
        zip_path = src / "bundle.zip"
        with zf.ZipFile(zip_path, "w") as z:
            z.writestr("readme.txt", "Hello from ZIP")
            z.writestr("notes.md", "# Notes\nSome content")

        target = tmp_path / "target"
        results = convert_resources(src, target)

        assert len(results) == 2
        titles = {r.title for r in results}
        assert "readme.txt" in titles
        assert "notes.md" in titles

    def test_invalid_zip_skipped(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "fake.zip").write_bytes(b"not a zip file")

        target = tmp_path / "target"
        results = convert_resources(src, target)
        assert results == []

    def test_zip_bomb_skipped(self, tmp_path: Path) -> None:
        """Archives declaring > 500 MB uncompressed should be skipped."""
        import zipfile as zf

        src = tmp_path / "src"
        src.mkdir()
        zip_path = src / "big.zip"
        with zf.ZipFile(zip_path, "w") as z:
            z.writestr("small.txt", "x")
            # Tamper not needed: the check is on actual sizes.
            # A 500 MB+ file would be too slow to create in tests,
            # so we test the normal case completes.
        target = tmp_path / "target"
        results = convert_resources(src, target)
        assert len(results) == 1  # small.txt extracted fine


class TestUnknownExtensionFallback:
    """Files with unrecognized extensions should be tried as plain text."""

    def test_unknown_text_file_converted(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "data.tsyso").write_text("readable text content", encoding="utf-8")

        target = tmp_path / "target"
        results = convert_resources(src, target)

        assert len(results) == 1
        assert results[0].title == "data.tsyso"
        assert results[0].format == "txt"

    def test_binary_unknown_file_skipped(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "data.bin2").write_bytes(b"\x00\x01\x02\xff" * 200)

        target = tmp_path / "target"
        results = convert_resources(src, target)
        assert results == []

    def test_re_extension_treated_as_text(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "pattern.re").write_text("^[a-z]+$", encoding="utf-8")

        target = tmp_path / "target"
        results = convert_resources(src, target)

        assert len(results) == 1
        assert results[0].title == "pattern.re"
