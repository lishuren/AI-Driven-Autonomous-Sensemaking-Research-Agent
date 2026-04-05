"""Source-code analysis — extract structure from code files for GraphRAG.

For **Python** files, uses the ``ast`` module to extract classes, functions,
imports, decorators, and docstrings.  For **other languages**, falls back to
``tree-sitter`` when installed, otherwise treats the file as plain text.

Public API
----------
``analyze_code(source_dir, target_dir, *, ignore_patterns)``
``analyze_code_files(path)``  — single-file convenience used by ``converter.py``
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path
from typing import Optional

from .converter import ConvertedDocument, _stable_filename, _build_metadata_header

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# tree-sitter availability
# ---------------------------------------------------------------------------

_HAS_TREE_SITTER = False
try:
    import tree_sitter  # noqa: F401
    _HAS_TREE_SITTER = True
except ImportError:
    pass

# Map file extension → tree-sitter language name.
_TS_LANG_MAP: dict[str, str] = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".cs": "c_sharp",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".lua": "lua",
}

# ---------------------------------------------------------------------------
# Python AST analysis
# ---------------------------------------------------------------------------

def _analyze_python(source: str, path: Path) -> str:
    """Extract structure from a Python source file via ``ast``."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        logger.debug("code_analyzer: cannot parse %s — %s", path.name, exc)
        return f"# {path.name}\n\n(Python file — syntax error, raw content follows)\n\n{source}"

    sections: list[str] = []
    sections.append(f"# Code Analysis: {path.name}")
    sections.append(f"Language: Python")
    sections.append(f"File: {path}")

    # Module docstring.
    module_doc = ast.get_docstring(tree)
    if module_doc:
        sections.append(f"\n## Module Documentation\n{module_doc}")

    # Imports.
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append(f"{module}.{alias.name}")
    if imports:
        sections.append("\n## Imports\n" + "\n".join(f"- {imp}" for imp in imports))

    # Top-level classes & functions.
    classes: list[str] = []
    functions: list[str] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(_describe_class(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_describe_function(node))

    if classes:
        sections.append("\n## Classes\n" + "\n\n".join(classes))
    if functions:
        sections.append("\n## Functions\n" + "\n\n".join(functions))

    # Relationships summary.
    calls = _extract_calls(tree)
    if calls:
        sections.append(
            "\n## Call Relationships\n"
            + "\n".join(f"- calls {c}" for c in sorted(calls)[:50])
        )

    return "\n".join(sections)


def _describe_class(node: ast.ClassDef) -> str:
    """Describe a class extracted via AST."""
    bases = [_name_of(b) for b in node.bases]
    decorators = [_name_of(d) for d in node.decorator_list]
    doc = ast.get_docstring(node) or ""

    lines = [f"### class {node.name}"]
    if bases:
        lines.append(f"Inherits: {', '.join(bases)}")
    if decorators:
        lines.append(f"Decorators: {', '.join(decorators)}")
    if doc:
        lines.append(f"\n{doc}")

    methods: list[str] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig = _function_signature(child)
            method_doc = ast.get_docstring(child) or ""
            desc = f"- `{sig}`"
            if method_doc:
                first_line = method_doc.split("\n")[0].strip()
                desc += f" — {first_line}"
            methods.append(desc)

    if methods:
        lines.append("\nMethods:")
        lines.extend(methods)

    return "\n".join(lines)


def _describe_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Describe a top-level function extracted via AST."""
    decorators = [_name_of(d) for d in node.decorator_list]
    doc = ast.get_docstring(node) or ""
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""

    sig = _function_signature(node)
    lines = [f"### {prefix}def {sig}"]
    if decorators:
        lines.append(f"Decorators: {', '.join(decorators)}")
    if doc:
        lines.append(f"\n{doc}")

    return "\n".join(lines)


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Build a function signature string."""
    args = node.args
    params: list[str] = []
    for arg in args.args:
        annotation = _name_of(arg.annotation) if arg.annotation else ""
        name = arg.arg
        params.append(f"{name}: {annotation}" if annotation else name)
    if args.vararg:
        params.append(f"*{args.vararg.arg}")
    for arg in args.kwonlyargs:
        annotation = _name_of(arg.annotation) if arg.annotation else ""
        name = arg.arg
        params.append(f"{name}: {annotation}" if annotation else name)
    if args.kwarg:
        params.append(f"**{args.kwarg.arg}")

    ret = ""
    if node.returns:
        ret = f" -> {_name_of(node.returns)}"

    return f"{node.name}({', '.join(params)}){ret}"


def _extract_calls(tree: ast.Module) -> set[str]:
    """Extract function/method call targets from the AST."""
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _name_of(node.func)
            if name:
                calls.add(name)
    return calls


def _name_of(node: Optional[ast.expr]) -> str:
    """Extract a dotted name from an AST node."""
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name_of(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Subscript):
        return _name_of(node.value)
    return ""


# ---------------------------------------------------------------------------
# tree-sitter analysis (generic fallback for non-Python languages)
# ---------------------------------------------------------------------------

def _analyze_with_tree_sitter(source: str, path: Path, lang_name: str) -> Optional[str]:
    """Use tree-sitter to extract structure from a source file."""
    if not _HAS_TREE_SITTER:
        return None

    try:
        import tree_sitter
        # Try to get the language grammar.
        lang_mod = __import__(f"tree_sitter_{lang_name.replace('-', '_')}", fromlist=["language"])
        language = tree_sitter.Language(lang_mod.language())
    except (ImportError, AttributeError, Exception) as exc:
        logger.debug(
            "code_analyzer: tree-sitter language %s not available — %s", lang_name, exc
        )
        return None

    parser = tree_sitter.Parser(language)
    tree = parser.parse(source.encode("utf-8"))
    root = tree.root_node

    sections: list[str] = [
        f"# Code Analysis: {path.name}",
        f"Language: {lang_name}",
        f"File: {path}",
    ]

    # Extract top-level declarations by node type.
    declarations: list[str] = []
    comments: list[str] = []

    for child in root.children:
        node_type = child.type
        text = child.text.decode("utf-8", errors="replace") if child.text else ""

        if "comment" in node_type:
            comments.append(text.strip())
        elif any(kw in node_type for kw in ("function", "method", "class", "interface", "struct", "enum", "module", "package")):
            # Truncate very long declarations to just the signature.
            lines = text.split("\n")
            if len(lines) > 5:
                signature = "\n".join(lines[:5]) + "\n  ..."
            else:
                signature = text
            declarations.append(f"### {node_type}\n```\n{signature}\n```")
        elif node_type in ("import_statement", "import_declaration", "use_declaration", "using_directive"):
            declarations.append(f"- import: {text.strip()}")

    if comments:
        top_comments = "\n".join(comments[:10])
        sections.append(f"\n## Comments\n{top_comments}")

    if declarations:
        sections.append("\n## Declarations\n" + "\n\n".join(declarations))

    return "\n".join(sections) if declarations or comments else None


# ---------------------------------------------------------------------------
# Fallback: plain text with language header
# ---------------------------------------------------------------------------

def _analyze_plain(source: str, path: Path) -> str:
    """Wrap raw source in a minimal structure header."""
    ext = path.suffix.lstrip(".")
    return (
        f"# Code: {path.name}\n"
        f"Language: {ext}\n"
        f"File: {path}\n\n"
        f"```{ext}\n{source}\n```"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_code_files(path: Path) -> Optional[str]:
    """Analyze a single source file and return structured text.

    Returns ``None`` if the file cannot be read.
    """
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("code_analyzer: cannot read %s — %s", path, exc)
        return None

    if not source.strip():
        return None

    ext = path.suffix.lower()

    # Python — native AST.
    if ext == ".py":
        return _analyze_python(source, path)

    # Other languages — try tree-sitter.
    lang_name = _TS_LANG_MAP.get(ext)
    if lang_name:
        result = _analyze_with_tree_sitter(source, path, lang_name)
        if result:
            return result

    # Fallback: structured plain text.
    return _analyze_plain(source, path)


def analyze_code(
    source_dir: str | Path,
    target_dir: str | Path,
    *,
    ignore_patterns: Optional[list[str]] = None,
) -> list[ConvertedDocument]:
    """Analyze all source code files in *source_dir* and write to *target_dir*.

    Parameters
    ----------
    source_dir:
        Directory containing source code files (scanned recursively).
    target_dir:
        GraphRAG project root.  Output text files go into ``<target_dir>/input/``.
    ignore_patterns:
        Glob patterns to skip (e.g. ``["__pycache__", "node_modules"]``).

    Returns
    -------
    list[ConvertedDocument]
        One record per successfully analysed file.
    """
    from .converter import _CODE_EXTENSIONS, _MAX_CONTENT_CHARS

    src = Path(source_dir)
    if not src.is_dir():
        logger.warning("code_analyzer: source directory does not exist — %s", src)
        return []

    output_dir = Path(target_dir) / "input"
    output_dir.mkdir(parents=True, exist_ok=True)

    skip_patterns = set(ignore_patterns or [])
    skip_patterns |= {"__pycache__", "node_modules", ".git", ".venv", "venv", ".tox", "dist", "build", "*.egg-info"}

    results: list[ConvertedDocument] = []

    for f in sorted(src.rglob("*")):
        if not f.is_file():
            continue

        # Check skip patterns.
        rel_parts = f.relative_to(src).parts
        if any(
            any(re.match(pat.replace("*", ".*"), part) for pat in skip_patterns)
            for part in rel_parts
        ):
            continue

        ext = f.suffix.lower()
        if f.name in ("Makefile", "Dockerfile"):
            ext = f".{f.name}"

        if ext not in _CODE_EXTENSIONS:
            continue

        text = analyze_code_files(f)
        if not text or not text.strip():
            continue

        if len(text) > _MAX_CONTENT_CHARS:
            text = text[:_MAX_CONTENT_CHARS]

        header = _build_metadata_header(f)
        full_text = header + text

        out_name = _stable_filename(f)
        out_path = output_dir / out_name
        out_path.write_text(full_text, encoding="utf-8")

        results.append(ConvertedDocument(
            source_path=str(f.resolve()),
            target_path=str(out_path.resolve()),
            title=f.name,
            char_count=len(text),
            format="code",
            metadata={"language": ext.lstrip("."), "size_bytes": f.stat().st_size},
        ))

    logger.info("code_analyzer: analysed %d code files from %s", len(results), src)
    return results
