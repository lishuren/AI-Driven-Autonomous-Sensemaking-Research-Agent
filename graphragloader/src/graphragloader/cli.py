"""CLI entry point for graphragloader.

Commands
--------
- ``graphragloader convert`` — convert files to text for GraphRAG
- ``graphragloader index``   — convert + build GraphRAG index
- ``graphragloader query``   — query a completed index
- ``graphragloader init``    — generate settings.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="graphragloader",
        description="Convert local files and build a GraphRAG knowledge graph index.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # --- convert ---
    p_convert = sub.add_parser("convert", help="Convert files to text for GraphRAG.")
    p_convert.add_argument("--source", required=True, help="Source resources directory.")
    p_convert.add_argument("--target", required=True, help="GraphRAG project root.")
    p_convert.add_argument("--include-code", action="store_true", help="Analyse source code files.")
    p_convert.add_argument("--max-chars", type=int, default=200_000, help="Max chars per document.")
    p_convert.add_argument("--force", action="store_true", help="Re-convert all files even if output already exists.")

    # --- index ---
    p_index = sub.add_parser("index", help="Convert files and build GraphRAG index.")
    p_index.add_argument("--source", required=True, help="Source resources directory.")
    p_index.add_argument("--target", required=True, help="GraphRAG project root.")
    p_index.add_argument("--include-code", action="store_true", help="Analyse source code files.")
    p_index.add_argument("--method", default="standard", choices=["standard", "fast"], help="Indexing method.")
    p_index.add_argument("--force", action="store_true", help="Force re-index even if no changes.")
    # LLM settings for auto-generating settings.yaml.
    p_index.add_argument("--provider", default="ollama", help="LLM provider (ollama, openai, etc.).")
    p_index.add_argument("--model", default="qwen2.5:7b", help="LLM model name.")
    p_index.add_argument("--api-base", default=None, help="LLM API base URL.")
    p_index.add_argument("--api-key", default=None, help="LLM API key.")
    p_index.add_argument("--embedding-model", default=None, help="Embedding model name.")
    p_index.add_argument("--request-timeout", type=int, default=1800, help="LLM request timeout in seconds (default 1800).")

    # --- query ---
    p_query = sub.add_parser("query", help="Query a completed GraphRAG index.")
    p_query.add_argument("--target", required=True, help="GraphRAG project root.")
    p_query.add_argument("--question", required=True, help="Query string.")
    p_query.add_argument(
        "--method", default="local",
        choices=["local", "global", "drift", "basic"],
        help="Search method.",
    )
    p_query.add_argument("--community-level", type=int, default=2, help="Community level.")
    p_query.add_argument("--response-type", default="Multiple Paragraphs", help="Response format.")

    # --- init ---
    p_init = sub.add_parser("init", help="Generate settings.yaml for a GraphRAG project.")
    p_init.add_argument("--target", required=True, help="GraphRAG project root.")
    p_init.add_argument("--provider", default="ollama", help="LLM provider.")
    p_init.add_argument("--model", default="qwen2.5:7b", help="LLM model name.")
    p_init.add_argument("--api-base", default=None, help="LLM API base URL.")
    p_init.add_argument("--api-key", default=None, help="LLM API key.")
    p_init.add_argument("--embedding-model", default=None, help="Embedding model name.")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing settings.yaml.")
    p_init.add_argument("--request-timeout", type=int, default=1800, help="LLM request timeout in seconds (default 1800).")

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "convert":
        return _cmd_convert(args)
    elif args.command == "index":
        return asyncio.run(_cmd_index(args))
    elif args.command == "query":
        return asyncio.run(_cmd_query(args))
    elif args.command == "init":
        return _cmd_init(args)

    parser.print_help()
    return 1


def _cmd_convert(args: argparse.Namespace) -> int:
    from .converter import convert_resources

    results = convert_resources(
        args.source,
        args.target,
        include_code=args.include_code,
        max_chars=args.max_chars,
        force=args.force,
    )
    converted = [r for r in results if not r.metadata.get("skipped")]
    skipped_count = len(results) - len(converted)
    msg = f"Converted {len(converted)} files"
    if skipped_count:
        msg += f", skipped {skipped_count} (already up to date)"
    print(f"{msg} \u2192 {args.target}/input/")
    for doc in converted:
        print(f"  {doc.title} ({doc.char_count:,} chars, {doc.format})")
    return 0


async def _cmd_index(args: argparse.Namespace) -> int:
    from .indexer import index
    from .settings import SettingsConfig

    settings_config = SettingsConfig(
        llm_provider=args.provider,
        llm_model=args.model,
        llm_api_base=args.api_base,
        llm_api_key=args.api_key,
        embedding_model=args.embedding_model,
        request_timeout=args.request_timeout,
    )

    result = await index(
        target_dir=args.target,
        source_dir=args.source,
        include_code=args.include_code,
        method=args.method,
        force=args.force,
        settings_config=settings_config,
        verbose=args.verbose,
    )

    if result.success:
        print(f"Indexing complete: {result.documents_converted} documents converted, "
              f"method={result.method}")
        if result.details:
            print(f"  Workflows completed: {result.details.get('workflows_completed', '?')}")
    else:
        print(f"Indexing FAILED: {result.error}", file=sys.stderr)
        return 1
    return 0


async def _cmd_query(args: argparse.Namespace) -> int:
    from .query import query

    result = await query(
        target_dir=args.target,
        question=args.question,
        method=args.method,
        community_level=args.community_level,
        response_type=args.response_type,
        verbose=args.verbose,
    )

    if result.content.startswith("Error:"):
        print(result.content, file=sys.stderr)
        return 1

    print(result.content)
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    from .settings import SettingsConfig, generate_settings

    config = SettingsConfig(
        llm_provider=args.provider,
        llm_model=args.model,
        llm_api_base=args.api_base,
        llm_api_key=args.api_key,
        embedding_model=args.embedding_model,
        request_timeout=args.request_timeout,
    )

    path = generate_settings(args.target, config=config, force=args.force)
    print(f"Generated: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
