from __future__ import annotations

import json
import errno
import os
import pathlib
import tempfile
import threading
import time
from contextlib import contextmanager

_EVENT_LOCK = threading.RLock()
from typing import Any, Mapping

from cgkn.execution import BlockExecutionResult

from .models import EventRecord, ProjectState, RunState


class StateStoreError(RuntimeError):
    pass


def _read_snapshot(path: pathlib.Path):
    """Read a complete snapshot despite a transient Windows replace/share race.

    Only explicitly identified Windows sharing/access errors are retried. Missing
    files, malformed JSON and persistent denial still fail closed. No fallback to
    an older snapshot, state mutation or task replay occurs.
    """
    deadline=time.monotonic()+2
    while True:
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except PermissionError as exc:
            # CRT-backed file open may expose EACCES without a winerror value.
            windows_denial=(getattr(exc,'winerror',None) in {5,32,33}
                            or (os.name=='nt' and exc.errno==errno.EACCES))
            if not windows_denial or time.monotonic()>=deadline:
                raise
            time.sleep(.01)


class FileRunStore:
    def __init__(self, run_root: pathlib.Path | str):
        self.root = pathlib.Path(run_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def exclusive_run(self, project_id, run_id):
        """One state coordinator per run, including across OS processes."""
        path = self.run_dir(project_id, run_id) / 'coordinator.lock'
        with self.exclusive_file(path):
            yield

    @contextmanager
    def exclusive_file(self, path, *, wait_seconds=0):
        path = pathlib.Path(path).resolve()
        if self.root not in path.parents:
            raise StateStoreError('lock path escapes state root')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a+b') as handle:
            if path.stat().st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            deadline = time.monotonic() + wait_seconds
            while True:
                try:
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise StateStoreError('run already has an active coordinator') from exc
                    time.sleep(.01)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

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
        if not value or value in {".", ".."} or pathlib.Path(value).name != value or any(sep in value for sep in ("/", "\\", ":", "\x00")) or value.endswith((".", " ")) or pathlib.PureWindowsPath(value).is_reserved():
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
            # Windows readers can briefly deny delete-sharing while reading an
            # otherwise valid snapshot. Retry only that transient OS condition;
            # retain atomic replacement and never truncate the live authority.
            deadline = time.monotonic() + 2
            while True:
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError as exc:
                    if os.name != 'nt' or getattr(exc,'winerror',None) not in {5,32,33} or time.monotonic() >= deadline:
                        raise
                    time.sleep(.01)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def immutable_json(self, path: pathlib.Path, value: Mapping[str, Any]) -> None:
        """Idempotent immutable record with an OS lock, not check-then-overwrite."""
        path = pathlib.Path(path)
        with self.exclusive_file(path.with_name(path.name + '.lock'), wait_seconds=10):
            if path.exists():
                if json.loads(path.read_text(encoding='utf-8')) != value:
                    raise ValueError('conflicting immutable record: ' + path.name)
                return
            self.atomic_json(path, value)

    def immutable_blob(self, path, content):
        path=pathlib.Path(path)
        if not path.resolve().is_relative_to(self.root) or path.is_symlink():
            raise StateStoreError('evidence path escapes state root')
        with self.exclusive_file(path.with_name(path.name+'.lock'),wait_seconds=10):
            if path.exists():
                if path.read_bytes()!=content:raise StateStoreError('conflicting evidence blob')
                return
            path.parent.mkdir(parents=True,exist_ok=True)
            fd,tmp=tempfile.mkstemp(dir=path.parent)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(content);stream.flush();os.fsync(stream.fileno())
                os.replace(tmp,path)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)

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
            return RunState.from_dict(_read_snapshot(path))
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
        with self.exclusive_file(run_dir / 'attempts' / result.node_id / 'record.lock', wait_seconds=10):
            if attempt_path.exists():
                raise StateStoreError(f"attempt result already exists: {result.attempt_id}")
            self.atomic_json(attempt_path, result.as_dict())
            previous = _read_snapshot(latest_path) if latest_path.exists() else None
            if previous is None or previous['attempt_id'] < result.attempt_id:
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
            return BlockExecutionResult.from_dict(_read_snapshot(path))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise StateStoreError(f"cannot load node result: {exc}") from exc

    def append_event(self, event: EventRecord) -> pathlib.Path:
        path = self.run_dir(event.project_id, event.run_id) / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with _EVENT_LOCK, path.open("a", encoding="utf-8", newline="\n") as handle:
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
