"""Application entry points for the sensemaking agent.

Usage
-----
::

    # From inside sensemaking-agent/
    python -m sensemaking_agent --query "lithium supply chain risks"
    python -m sensemaking_agent --topic-dir ../topicexample
    python -m sensemaking_agent --query "CRISPR gene editing mechanisms" --max-iterations 3

Environment variables
---------------------
``TAVILY_API_KEY``
    Tavily API key for web search.  Required for live runs.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional


def _load_dotenv(env_path: Path) -> None:
    """Load key=value pairs from *env_path* into ``os.environ`` (no-op if file absent)."""
    if not env_path.exists():
        return
    with env_path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


# Resolve .env relative to the sensemaking-agent/ package root (3 levels up from this file).
# Falls back to .env in the current working directory.
_DOTENV_FROM_MODULE = Path(__file__).parent.parent.parent / ".env"
_load_dotenv(_DOTENV_FROM_MODULE)
if not _DOTENV_FROM_MODULE.exists():
    _load_dotenv(Path.cwd() / ".env")

from .budget import BudgetTracker
from .config import AgentConfig
from .database import RunArtifactStore
from .state import build_initial_state
from .tools.scout_tool import ScoutTool
from .tools.scraper_tool import (
    ScraperTool,
    reset_runtime_state as reset_scraper_runtime_state,
    set_no_scrape,
    set_respect_robots,
)
from .tools.search_tool import (
    SearchTool,
    reset_runtime_state as reset_search_runtime_state,
    set_budget,
    set_dry_run,
)
from .tools.resource_loader import load_resources
from .workflow import build_workflow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Requirements-file and topic-directory parsing
# ---------------------------------------------------------------------------

def _parse_requirements_file(path: Path) -> tuple[str, Optional[str]]:
    """Parse a requirements Markdown file and extract *query* and *user_prompt*.

    Supports ``## Topic``, ``## Research Focus``, ``## Background`` section
    markers.  The ``## Topic`` section becomes the query string.  All other
    non-prompt sections are joined as background context (*user_prompt*).

    If no section markers are found and the file starts with a Markdown heading
    (``#``, ``##``, or ``###``), the heading text becomes the query and the
    full file content becomes background context.

    Returns ``(query, user_prompt)``.
    """
    raw = path.read_text(encoding="utf-8").strip()

    # Try section-based parsing.
    sections: dict[str, str] = {}
    current_section: Optional[str] = None
    current_lines: list[str] = []
    non_section_lines: list[str] = []

    for line in raw.split("\n"):
        heading_match = re.match(r"^##\s+(.+)$", line)
        if heading_match:
            if current_section is not None:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = heading_match.group(1).strip().lower()
            current_lines = []
        elif current_section is not None:
            current_lines.append(line)
        else:
            non_section_lines.append(line)

    if current_section is not None:
        sections[current_section] = "\n".join(current_lines).strip()

    user_prompt: Optional[str] = None

    if "topic" in sections:
        query = sections["topic"]
        context_parts: list[str] = []
        for key, val in sections.items():
            if key not in {"topic", "prompt"} and val:
                context_parts.append(val)
        context = "\n\n".join(context_parts)
        user_prompt = context or None
    elif sections:
        # Has section markers but no ## Topic — combine everything.
        parts = ["\n".join(non_section_lines).strip()]
        for key, val in sections.items():
            if key != "prompt" and val:
                parts.append(val)
        query = "\n\n".join(p for p in parts if p)
    else:
        # No section markers.
        first_line = raw.split("\n")[0].strip()
        heading_match = re.match(r"^#{1,3}\s+(.+)$", first_line)
        if heading_match:
            query = heading_match.group(1).strip()
            user_prompt = raw
        else:
            query = raw

    if not query:
        query = raw

    return query, user_prompt


def _parse_topic_dir(
    folder: Path,
) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Parse a self-contained topic directory.

    Returns ``(query, user_prompt, prompt_dir, resources_dir)``.

    Convention:
    - ``requirements.md`` → ``topic.md`` → first ``*.md`` for the topic spec.
    - ``prompts/`` sub-folder → custom prompt template overrides.
    - ``resources/`` sub-folder → local research documents.
    """
    prompt_dir: Optional[str] = None
    prompts_sub = folder / "prompts"
    if prompts_sub.is_dir():
        prompt_dir = str(prompts_sub)

    resources_dir: Optional[str] = None
    resources_sub = folder / "resources"
    if resources_sub.is_dir():
        resources_dir = str(resources_sub)

    md_file: Optional[Path] = None
    for candidate in ("requirements.md", "topic.md"):
        if (folder / candidate).is_file():
            md_file = folder / candidate
            break

    if md_file is None:
        for p in sorted(folder.glob("*.md")):
            if p.name.lower() == "readme.md":
                continue
            md_file = p
            break

    if md_file is not None:
        query, user_prompt = _parse_requirements_file(md_file)
    else:
        query = folder.name
        user_prompt = None

    return query, user_prompt, prompt_dir, resources_dir


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sensemaking_agent",
        description="AI-Driven Autonomous Sensemaking Research Agent",
    )

    topic_group = parser.add_mutually_exclusive_group(required=True)
    topic_group.add_argument(
        "--query",
        metavar="QUERY",
        help="Research question or topic to investigate.",
    )
    topic_group.add_argument(
        "--topic-dir",
        metavar="DIR",
        help="Path to a self-contained research folder.  The agent reads the "
             "topic from requirements.md (or topic.md / first *.md).  If a "
             "'prompts/' sub-folder exists it overrides the bundled prompt "
             "templates.  A 'resources/' sub-folder supplies local documents.  "
             "All output is written to an 'output/' sub-folder created "
             "automatically.",
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
    parser.add_argument(
        "--output-dir",
        default=str(Path("data") / "runs"),
        metavar="DIR",
        help="Directory where JSON checkpoints and final run artifacts are written (default: data/runs).",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Disable writing run checkpoints and final artifacts to disk.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Disable live Tavily search and extract calls for an offline orchestration run.",
    )
    parser.add_argument(
        "--tavily-key",
        metavar="KEY",
        help="Tavily API key override for this run.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        metavar="N",
        help="Maximum Tavily search results to request per query.",
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        metavar="N",
        help="Maximum Tavily search or extract API calls for this run.",
    )
    parser.add_argument(
        "--max-credits",
        type=float,
        metavar="CREDITS",
        help="Maximum Tavily credits to spend for this run.",
    )
    parser.add_argument(
        "--warn-threshold",
        type=float,
        metavar="FRACTION",
        help="Warn when budget usage reaches this fraction of a configured limit.",
    )
    parser.add_argument(
        "--no-scrape",
        action="store_true",
        help="Disable the Playwright fallback scraper for this run.",
    )
    robots_group = parser.add_mutually_exclusive_group()
    robots_group.add_argument(
        "--respect-robots",
        dest="respect_robots",
        action="store_true",
        help="Enable the advisory robots.txt check before scraping.",
    )
    robots_group.add_argument(
        "--no-respect-robots",
        dest="respect_robots",
        action="store_false",
        help="Disable the advisory robots.txt check before scraping.",
    )
    parser.set_defaults(respect_robots=None)
    parser.add_argument(
        "--prompt-dir",
        metavar="DIR",
        help="Directory containing custom prompt template overrides. Files present here "
             "take precedence over the bundled prompts/ directory.",
    )
    return parser


def _resolve_agent_config(
    *,
    tavily_key: str | None = None,
    max_results: int | None = None,
    max_queries: int | None = None,
    max_credits: float | None = None,
    warn_threshold: float | None = None,
    no_scrape: bool | None = None,
    respect_robots: bool | None = None,
) -> AgentConfig:
    """Return runtime configuration with explicit overrides applied."""
    config = AgentConfig()

    if tavily_key:
        config.search.tavily_api_key = tavily_key.strip()
    if max_results is not None:
        config.search.max_results = max_results
    if max_queries is not None:
        config.budget.max_queries = max_queries
    if max_credits is not None:
        config.budget.max_credits = max_credits
    if warn_threshold is not None:
        config.budget.warn_threshold = warn_threshold
    if no_scrape is not None:
        config.scraper.no_scrape = no_scrape
    if respect_robots is not None:
        config.scraper.respect_robots = respect_robots

    return config


def _configure_runtime(
    config: AgentConfig,
    *,
    dry_run: bool,
) -> tuple[ScoutTool, BudgetTracker]:
    """Apply runtime controls and return the configured Scout tool and budget."""
    budget_tracker = BudgetTracker(
        max_queries=config.budget.max_queries,
        max_credits=config.budget.max_credits,
        warn_threshold=config.budget.warn_threshold,
    )
    set_budget(budget_tracker)
    set_dry_run(dry_run)
    set_no_scrape(config.scraper.no_scrape)
    set_respect_robots(config.scraper.respect_robots)

    search_tool = SearchTool(max_results=config.search.max_results)
    scout_tool = ScoutTool(
        search_tool=search_tool,
        scraper_tool=ScraperTool(),
    )
    return scout_tool, budget_tracker


async def run(
    query: str,
    max_iterations: int,
    *,
    output_dir: str | Path | None = Path("data") / "runs",
    dry_run: bool = False,
    tavily_key: str | None = None,
    max_results: int | None = None,
    max_queries: int | None = None,
    max_credits: float | None = None,
    warn_threshold: float | None = None,
    no_scrape: bool | None = None,
    respect_robots: bool | None = None,
    prompt_dir: str | None = None,
    user_prompt: str | None = None,
    resources_dir: str | None = None,
) -> str:
    """Build and invoke the sensemaking workflow for *query*.

    Returns the ``final_synthesis`` string from the completed state.
    """
    from .graph import RouterConfig

    router_config = RouterConfig(max_iterations=max_iterations)
    artifact_store = None

    # Pre-load local resource documents when a resources directory is provided.
    seed_docs: list[dict[str, object]] = []
    if resources_dir:
        resource_documents = load_resources(resources_dir)
        seed_docs = [doc.model_dump(mode="json") for doc in resource_documents]
        if seed_docs:
            logger.info(
                "Loaded %d local resource documents from %s.",
                len(seed_docs),
                resources_dir,
            )

    initial_state = build_initial_state(
        query,
        documents=seed_docs or None,
        user_prompt=user_prompt,
    )
    agent_config = _resolve_agent_config(
        tavily_key=tavily_key,
        max_results=max_results,
        max_queries=max_queries,
        max_credits=max_credits,
        warn_threshold=warn_threshold,
        no_scrape=no_scrape,
        respect_robots=respect_robots,
    )

    previous_tavily_key = os.environ.get("TAVILY_API_KEY")
    reset_search_runtime_state()
    reset_scraper_runtime_state()

    try:
        if agent_config.search.tavily_api_key:
            os.environ["TAVILY_API_KEY"] = agent_config.search.tavily_api_key

        scout_tool, budget_tracker = _configure_runtime(
            agent_config,
            dry_run=dry_run,
        )

        if dry_run:
            logger.info("Dry-run enabled: Tavily search and extract calls are disabled.")
        if agent_config.scraper.no_scrape:
            logger.info("Playwright scraping disabled for this run.")
        if not agent_config.scraper.respect_robots:
            logger.info("robots.txt advisory checks disabled for this run.")

        if output_dir is not None:
            artifact_store = RunArtifactStore.find_latest_resumable_run(output_dir, query)
            if artifact_store is not None:
                initial_state = artifact_store.load_resume_state()
                artifact_store.record_resume()
                logger.info(
                    "Resuming existing run from %s at iteration %d.",
                    artifact_store.run_dir,
                    initial_state.get("iteration_count", 0),
                )
            else:
                artifact_store = RunArtifactStore(
                    base_dir=output_dir,
                    query=query,
                    max_iterations=max_iterations,
                )
                logger.info("Writing run artifacts to %s", artifact_store.run_dir)
                artifact_store.save_initial_state(initial_state)

        if prompt_dir is not None:
            logger.info("Custom prompt directory: %s", prompt_dir)

        workflow = build_workflow(
            scout_tool=scout_tool,
            router_config=router_config,
            llm_config=agent_config.llm,
            artifact_store=artifact_store,
            prompt_dir=prompt_dir,
        )

        logger.info("Starting sensemaking run for query: %r", query)
        final_state = await workflow.ainvoke(initial_state)
        if artifact_store is not None:
            final_state_path = artifact_store.run_dir / "final_state.json"
            if not final_state_path.exists():
                artifact_store.save_final(final_state)

        if (
            agent_config.budget.max_queries is not None
            or agent_config.budget.max_credits is not None
            or budget_tracker.queries_used > 0
            or budget_tracker.credits_used > 0
        ):
            logger.info("Budget summary: %s", budget_tracker.summary())

        synthesis: str = final_state.get("final_synthesis", "")
        return synthesis
    finally:
        reset_search_runtime_state()
        reset_scraper_runtime_state()
        if previous_tavily_key is None:
            os.environ.pop("TAVILY_API_KEY", None)
        else:
            os.environ["TAVILY_API_KEY"] = previous_tavily_key


def main() -> None:
    """CLI entry point registered as ``sensemaking-agent`` in pyproject.toml."""
    parser = _build_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    # --- Resolve topic source ------------------------------------------------
    query: str
    user_prompt: str | None = None
    prompt_dir: str | None = None
    resources_dir: str | None = None
    output_dir: str | Path | None

    if args.topic_dir is not None:
        topic_dir = Path(args.topic_dir)
        if not topic_dir.is_dir():
            sys.exit(f"Topic directory not found: {args.topic_dir!r}")

        # Load .env from topic dir *before* run() so it takes precedence over
        # the project-level .env already loaded at module import time.
        _load_dotenv(topic_dir / ".env")

        query, user_prompt, dir_prompt_dir, resources_dir = _parse_topic_dir(topic_dir)

        # Convention: output always goes to <topic_dir>/output/
        output_dir = None if args.no_persist else str(topic_dir / "output")

        # Convention: prompt overrides from topic dir unless explicit --prompt-dir
        prompt_dir = args.prompt_dir or dir_prompt_dir
    else:
        query = args.query
        output_dir = None if args.no_persist else args.output_dir
        prompt_dir = args.prompt_dir

    # CLI / env fallback for prompt_dir.
    prompt_dir = prompt_dir or os.environ.get("SENSEMAKING_PROMPT_DIR") or None

    result = asyncio.run(
        run(
            query,
            args.max_iterations,
            output_dir=output_dir,
            dry_run=args.dry_run,
            tavily_key=args.tavily_key,
            max_results=args.max_results,
            max_queries=args.max_queries,
            max_credits=args.max_credits,
            warn_threshold=args.warn_threshold,
            no_scrape=True if args.no_scrape else None,
            respect_robots=args.respect_robots,
            prompt_dir=prompt_dir,
            user_prompt=user_prompt,
            resources_dir=resources_dir,
        )
    )
    print(result)


if __name__ == "__main__":  # pragma: no cover
    main()