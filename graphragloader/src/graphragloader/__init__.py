"""graphragloader — convert diverse local files into a GraphRAG knowledge graph."""

from __future__ import annotations

__version__ = "0.1.0"

from .converter import ConvertedDocument, convert_resources
from .code_analyzer import analyze_code, analyze_code_files
from .indexer import IndexResult, index
from .query import QueryResult, query
from .settings import SettingsConfig, generate_settings

__all__ = [
    "ConvertedDocument",
    "IndexResult",
    "QueryResult",
    "SettingsConfig",
    "analyze_code",
    "analyze_code_files",
    "convert_resources",
    "generate_settings",
    "index",
    "query",
]
