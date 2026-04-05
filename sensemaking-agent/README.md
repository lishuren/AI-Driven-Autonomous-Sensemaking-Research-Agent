# Sensemaking Agent Package

This package contains the implementation scaffold for the
AI-Driven Autonomous Sensemaking Research Agent.

Current scope:

- project packaging and test configuration
- canonical state models and helpers
- graph export utilities
- route-decision logic aligned with the sensemaking loop docs
- Scout acquisition tooling and LangGraph workflow wiring
- LLM-backed Analyst and Critic nodes
- prompt-driven Writer synthesis with deterministic fallback behavior
- per-run artifact persistence with automatic resume
- visualization exports for GraphML, DOT, and HTML inspection
- CLI runtime controls for dry-run, budget, Tavily key override, and scraper behavior
- GraphRAG local-corpus integration via `graphragloader` companion package
- comprehensive offline test coverage across state, tools, nodes, workflow, persistence, visualization, and LLM transport

Planned next layers:

- checked-in live-run verification guidance
- richer graph rendering and inspection workflows
- broader live-backend integration coverage
- end-to-end live validation of GraphRAG index + query pipeline