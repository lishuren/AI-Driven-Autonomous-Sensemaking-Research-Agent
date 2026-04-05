"""LangGraph workflow builder for the sensemaking agent.

Assembles the Scout → Analyst → Critic → Router → Writer state graph.
The Router uses LangGraph ``Command`` to dynamically select the next node,
allowing the workflow to loop back to Scout for additional evidence when
contradictions or gaps remain open.

Graph topology
--------------
::

    __start__ ──► scout ──► analyst ──► critic ──► router
                  ▲                                  │
                  │   continue_research / resolve_*  │
                  └──────────────────────────────────┘
                                                     │ finalize
                                                     ▼
                                                   writer ──► __end__

Public API
----------
``build_workflow()``  — returns a compiled ``CompiledStateGraph``.
``build_initial_state()``  — re-exported from ``sensemaking_agent.state``
                             for convenience.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, StateGraph

from .config import LLMConfig
from .graph import RouterConfig
from .nodes.analyst_node import make_analyst_node
from .nodes.critic_node import make_critic_node
from .nodes.router_node import make_router_node
from .nodes.scout_node import make_scout_node
from .nodes.writer_node import make_writer_node
from .state import ResearchState
from .tools.scout_tool import ScoutTool

if TYPE_CHECKING:
    from .database import RunArtifactStore

logger = logging.getLogger(__name__)


def build_workflow(
    *,
    scout_tool: ScoutTool | None = None,
    graphrag_tool: Any | None = None,
    router_config: RouterConfig | None = None,
    llm_config: LLMConfig | None = None,
    artifact_store: RunArtifactStore | None = None,
    prompt_dir: str | None = None,
) -> Any:
    """Build and compile the sensemaking state graph.

    Parameters
    ----------
    scout_tool:
        Optional pre-configured ``ScoutTool``.  A default instance (which
        reads ``TAVILY_API_KEY`` from the environment) is created when omitted.
    graphrag_tool:
        Optional ``GraphRAGTool`` instance for querying a local GraphRAG index.
        When provided, the Scout node merges GraphRAG results with web search.
    router_config:
        Optional ``RouterConfig`` controlling iteration and saturation
        thresholds.  Defaults are used when omitted.

    Returns
    -------
    CompiledStateGraph
        A compiled LangGraph workflow ready to be invoked or streamed.
    """
    graph = StateGraph(ResearchState)

    # Register nodes.
    graph.add_node("scout", make_scout_node(scout_tool, graphrag_tool=graphrag_tool))
    graph.add_node("analyst", make_analyst_node(llm_config, prompt_dir))
    graph.add_node("critic", make_critic_node(llm_config, prompt_dir))
    graph.add_node("router", make_router_node(router_config, artifact_store=artifact_store))
    graph.add_node("writer", make_writer_node(llm_config, artifact_store, prompt_dir))

    # Fixed edges: Scout → Analyst → Critic → Router.
    graph.set_entry_point("scout")
    graph.add_edge("scout", "analyst")
    graph.add_edge("analyst", "critic")
    graph.add_edge("critic", "router")

    # Router uses Command to dynamically choose "scout" or "writer".
    # Writer always ends the workflow.
    graph.add_edge("writer", END)

    return graph.compile()
