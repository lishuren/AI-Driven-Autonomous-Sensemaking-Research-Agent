from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..state import state_to_digraph, validate_state
from ..visualisation import export_visualizations

_DEFAULT_RUN_SLUG = "research-run"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _slugify(value: str, *, max_length: int = 60) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug:
        return _DEFAULT_RUN_SLUG
    return slug[:max_length].rstrip("-") or _DEFAULT_RUN_SLUG


@dataclass(slots=True)
class RunArtifactStore:
    """Persist JSON checkpoints and final run artifacts for a workflow run."""

    base_dir: str | Path
    query: str
    max_iterations: int
    run_id: str = field(init=False)
    run_dir: Path = field(init=False)
    _manifest: dict[str, Any] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        query = self.query.strip()
        if not query:
            raise ValueError("query must not be empty")

        timestamp = _utc_now()
        timestamp_slug = timestamp.strftime("%Y%m%dT%H%M%SZ")
        run_slug = _slugify(query)

        base_dir = Path(self.base_dir)
        base_dir.mkdir(parents=True, exist_ok=True)

        run_id = f"{timestamp_slug}-{run_slug}"
        run_dir = base_dir / run_id
        suffix = 1
        while run_dir.exists():
            run_id = f"{timestamp_slug}-{run_slug}-{suffix:02d}"
            run_dir = base_dir / run_id
            suffix += 1

        run_dir.mkdir(parents=True, exist_ok=False)

        self.run_id = run_id
        self.run_dir = run_dir
        self._manifest = {
            "run_id": self.run_id,
            "query": query,
            "max_iterations": self.max_iterations,
            "started_at": timestamp.isoformat(),
            "checkpoint_files": [],
            "updated_at": timestamp.isoformat(),
        }
        self._write_json(self.run_dir / "run_manifest.json", self._manifest)

    @classmethod
    def open_existing(cls, run_dir: str | Path) -> "RunArtifactStore":
        run_path = Path(run_dir)
        manifest_path = run_path / "run_manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Run manifest not found: {manifest_path}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        query = str(manifest.get("query", "")).strip()
        if not query:
            raise ValueError(f"Run manifest missing query: {manifest_path}")

        store = object.__new__(cls)
        store.base_dir = run_path.parent
        store.query = query
        store.max_iterations = int(manifest.get("max_iterations", 0) or 0)
        store.run_id = str(manifest.get("run_id", run_path.name))
        store.run_dir = run_path
        store._manifest = manifest
        return store

    @classmethod
    def find_latest_resumable_run(
        cls,
        base_dir: str | Path,
        query: str,
    ) -> "RunArtifactStore | None":
        query = query.strip()
        if not query:
            return None

        base_path = Path(base_dir)
        if not base_path.exists():
            return None

        for child in sorted(base_path.iterdir(), key=lambda item: item.name, reverse=True):
            if not child.is_dir():
                continue
            try:
                store = cls.open_existing(child)
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                continue
            if store.query != query:
                continue
            if store.is_completed:
                continue
            return store

        return None

    @property
    def is_completed(self) -> bool:
        return bool(
            self._manifest.get("completed_at")
            or self._manifest.get("final_state_file")
            or (self.run_dir / "final_state.json").is_file()
        )

    def load_resume_state(self) -> dict[str, Any]:
        checkpoint_path = self._latest_checkpoint_path()
        if checkpoint_path is not None:
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            return validate_state(payload.get("state", {}))

        initial_state_path = self.run_dir / "initial_state.json"
        if initial_state_path.is_file():
            payload = json.loads(initial_state_path.read_text(encoding="utf-8"))
            return validate_state(payload)

        raise FileNotFoundError(
            f"No resumable state found in run directory: {self.run_dir}"
        )

    def record_resume(self) -> None:
        self._manifest["resume_count"] = int(self._manifest.get("resume_count", 0)) + 1
        self._manifest["last_resumed_at"] = _utc_now().isoformat()
        self._manifest["updated_at"] = _utc_now().isoformat()
        self._write_json(self.run_dir / "run_manifest.json", self._manifest)

    def save_initial_state(self, state: Mapping[str, Any]) -> Path:
        normalized = validate_state(state)
        path = self.run_dir / "initial_state.json"
        self._write_json(path, normalized)
        self._manifest["initial_state_file"] = path.name
        self._manifest["updated_at"] = _utc_now().isoformat()
        self._write_json(self.run_dir / "run_manifest.json", self._manifest)
        return path

    def save_checkpoint(
        self,
        state: Mapping[str, Any],
        *,
        route: str | None = None,
        reason: str | None = None,
    ) -> Path:
        normalized = validate_state(state)
        iteration = int(normalized.get("iteration_count", 0))
        file_name = f"checkpoint.iter-{iteration:03d}.json"
        payload = {
            "artifact_type": "checkpoint",
            "run_id": self.run_id,
            "saved_at": _utc_now().isoformat(),
            "iteration": iteration,
            "route": route,
            "reason": reason,
            "state": normalized,
        }
        path = self.run_dir / file_name
        self._write_json(path, payload)

        checkpoint_files = list(self._manifest.get("checkpoint_files", []))
        if file_name not in checkpoint_files:
            checkpoint_files.append(file_name)

        self._manifest["checkpoint_files"] = checkpoint_files
        self._manifest["last_checkpoint_iteration"] = iteration
        self._manifest["last_route"] = route
        self._manifest["updated_at"] = _utc_now().isoformat()
        self._write_json(self.run_dir / "run_manifest.json", self._manifest)
        return path

    def save_final(self, state: Mapping[str, Any]) -> None:
        normalized = validate_state(state)

        final_state_path = self.run_dir / "final_state.json"
        self._write_json(final_state_path, normalized)

        report_text = str(normalized.get("final_synthesis", "")).strip()
        report_path = self.run_dir / "report.md"
        if report_text:
            report_path.write_text(f"{report_text}\n", encoding="utf-8")

        graph_path = self.run_dir / "graph.json"
        self._write_json(graph_path, self._graph_payload(normalized))
        visualisation_paths = export_visualizations(
            normalized,
            output_dir=self.run_dir,
            title=str(normalized.get("current_query", "Sensemaking Graph")),
        )

        final_route = None
        route_history = normalized.get("route_history", [])
        if route_history:
            final_route = route_history[-1].get("route")

        self._manifest["completed_at"] = _utc_now().isoformat()
        self._manifest["final_state_file"] = final_state_path.name
        self._manifest["graph_file"] = graph_path.name
        self._manifest["graphml_file"] = visualisation_paths["graphml"].name
        self._manifest["dot_file"] = visualisation_paths["dot"].name
        self._manifest["html_viewer_file"] = visualisation_paths["html"].name
        if report_text:
            self._manifest["report_file"] = report_path.name
        self._manifest["final_iteration_count"] = int(normalized.get("iteration_count", 0))
        self._manifest["final_metrics"] = normalized.get("metrics", {})
        self._manifest["final_route"] = final_route
        self._manifest["updated_at"] = _utc_now().isoformat()
        self._write_json(self.run_dir / "run_manifest.json", self._manifest)

    def _latest_checkpoint_path(self) -> Path | None:
        checkpoint_files = list(self._manifest.get("checkpoint_files", []))
        for file_name in reversed(checkpoint_files):
            path = self.run_dir / str(file_name)
            if path.is_file():
                return path

        candidates = sorted(
            self.run_dir.glob("checkpoint.iter-*.json"),
            key=lambda item: item.name,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def _graph_payload(self, state: Mapping[str, Any]) -> dict[str, Any]:
        graph = state_to_digraph(state)
        return {
            "artifact_type": "graph",
            "run_id": self.run_id,
            "generated_at": _utc_now().isoformat(),
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "nodes": [
                {"id": node_id, **attrs}
                for node_id, attrs in graph.nodes(data=True)
            ],
            "edges": [
                {"source": source, "target": target, **attrs}
                for source, target, attrs in graph.edges(data=True)
            ],
        }

    def _write_json(self, path: Path, payload: Mapping[str, Any]) -> None:
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )