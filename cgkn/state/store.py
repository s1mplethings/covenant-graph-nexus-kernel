from __future__ import annotations

import json
import os
import pathlib
import tempfile
from typing import Any, Mapping

from cgkn.execution import BlockExecutionResult

from .models import EventRecord, ProjectState, RunState


class StateStoreError(RuntimeError):
    pass


class FileRunStore:
    def __init__(self, run_root: pathlib.Path | str):
        self.root = pathlib.Path(run_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, project_id: str, run_id: str) -> pathlib.Path:
        self._validate_segment(project_id)
        self._validate_segment(run_id)
        path = (self.root / project_id / run_id).resolve()
        if self.root != path and self.root not in path.parents:
            raise StateStoreError("run path escapes configured root")
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _validate_segment(value: str) -> None:
        if not value or value in {".", ".."} or pathlib.Path(value).name != value or any(sep in value for sep in ("/", "\\")):
            raise StateStoreError("invalid state identity path segment")

    def atomic_json(self, path: pathlib.Path, value: Mapping[str, Any]) -> None:
        path = pathlib.Path(path)
        try:
            path.resolve().relative_to(self.root)
        except ValueError as exc:
            raise StateStoreError("state write path escapes configured root") from exc
        if path.is_symlink():
            raise StateStoreError("state write target must not be a symlink")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save_project(self, value: ProjectState) -> pathlib.Path:
        path = self.run_dir(value.project_id, value.latest_run_id) / "project_state.json"
        self.atomic_json(path, value.as_dict())
        return path

    def save_run(self, value: RunState) -> pathlib.Path:
        path = self.run_dir(value.project_id, value.run_id) / "run_state.json"
        self.atomic_json(path, value.as_dict())
        return path

    def load_run(self, project_id: str, run_id: str) -> RunState:
        path = self.run_dir(project_id, run_id) / "run_state.json"
        try:
            return RunState.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise StateStoreError(f"cannot load run state: {exc}") from exc

    def save_definition(self, project_id: str, run_id: str, name: str, value: Mapping[str, Any]) -> pathlib.Path:
        if name not in {"capability_tree.json", "execution_dag.json"}:
            raise StateStoreError("unsupported definition name")
        path = self.run_dir(project_id, run_id) / name
        self.atomic_json(path, value)
        return path

    def save_result(self, result: BlockExecutionResult) -> pathlib.Path:
        self._validate_segment(result.node_id)
        self._validate_segment(result.attempt_id)
        run_dir = self.run_dir(result.project_id, result.run_id)
        attempt_path = run_dir / "attempts" / result.node_id / f"{result.attempt_id}.json"
        latest_path = run_dir / "node_results" / f"{result.node_id}.json"
        if attempt_path.exists():
            raise StateStoreError(f"attempt result already exists: {result.attempt_id}")
        self.atomic_json(attempt_path, result.as_dict())
        self.atomic_json(latest_path, result.as_dict())
        return attempt_path

    def save_agent_decision(self, project_id: str, run_id: str, number: int, value: Mapping[str, Any]) -> pathlib.Path:
        if number < 1:
            raise StateStoreError("agent decision number must be positive")
        path = self.run_dir(project_id, run_id) / "agent" / f"decision-{number:02d}.json"
        if path.exists():
            raise StateStoreError(f"agent decision already exists: {number}")
        self.atomic_json(path, value)
        return path

    def save_run_summary(self, project_id: str, run_id: str, value: Mapping[str, Any]) -> pathlib.Path:
        path = self.run_dir(project_id, run_id) / "run_summary.json"
        self.atomic_json(path, value)
        return path

    def load_result(self, project_id: str, run_id: str, node_id: str) -> BlockExecutionResult:
        self._validate_segment(node_id)
        path = self.run_dir(project_id, run_id) / "node_results" / f"{node_id}.json"
        try:
            return BlockExecutionResult.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise StateStoreError(f"cannot load node result: {exc}") from exc

    def append_event(self, event: EventRecord) -> pathlib.Path:
        path = self.run_dir(event.project_id, event.run_id) / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event.as_dict(), sort_keys=True, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return path

    def load_events(self, project_id: str, run_id: str) -> tuple[EventRecord, ...]:
        path = self.run_dir(project_id, run_id) / "events.jsonl"
        try:
            return tuple(EventRecord.from_dict(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise StateStoreError(f"cannot load event log: {exc}") from exc
