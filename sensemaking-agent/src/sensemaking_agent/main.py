"""Application entry points for the sensemaking agent.

Usage
-----
::

    # From inside sensemaking-agent/
    python -m sensemaking_agent --query "lithium supply chain risks"
    python -m sensemaking_agent --query "CRISPR gene editing mechanisms" --max-iterations 3

Environment variables
---------------------
``TAVILY_API_KEY``
    Tavily API key for web search.  Required for live runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .state import build_initial_state
from .workflow import build_workflow

logger = logging.getLogger(__name__)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sensemaking_agent",
        description="AI-Driven Autonomous Sensemaking Research Agent",
    )
    parser.add_argument(
        "--query",
        required=True,
        metavar="QUERY",
        help="Research question or topic to investigate.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        metavar="N",
        help="Maximum sensemaking loop iterations before forced finalization (default: 5).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return parser


async def run(query: str, max_iterations: int) -> str:
    """Build and invoke the sensemaking workflow for *query*.

    Returns the ``final_synthesis`` string from the completed state.
    """
    from .graph import RouterConfig

    config = RouterConfig(max_iterations=max_iterations)
    workflow = build_workflow(router_config=config)
    initial_state = build_initial_state(query)

    logger.info("Starting sensemaking run for query: %r", query)
    final_state = await workflow.ainvoke(initial_state)
    synthesis: str = final_state.get("final_synthesis", "")
    return synthesis


def main() -> None:
    """CLI entry point registered as ``sensemaking-agent`` in pyproject.toml."""
    parser = _build_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    result = asyncio.run(run(args.query, args.max_iterations))
    print(result)


if __name__ == "__main__":  # pragma: no cover
    main()