from __future__ import annotations

import json
import os
import pathlib
import re
import tempfile
from typing import Any, Iterable

from cgkn.execution.contracts import utc_now

from .contracts import LearningEvent, LessonContext, LessonQuery, LessonRecord, LessonStatus, canonical_hash


_SECRET_KEYS = re.compile(r"(?i)(api[_-]?key|authorization|bearer|credential|password|secret|token)")


def _reject_credentials(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _SECRET_KEYS.search(str(key)) and item not in (None, "", False, 0, "UNKNOWN"):
                raise ValueError(f"credential-like field rejected: {path}{key}")
            _reject_credentials(item, f"{path}{key}.")
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_credentials(item, path)


class FileLessonStore:
    def __init__(self, artifact_root: pathlib.Path | str):
        base = pathlib.Path(artifact_root).resolve()
        self.root = base if base.name == "learning" else base / "learning"
        self.events_path = self.root / "events.jsonl"
        self.revisions_path = self.root / "lesson_revisions.jsonl"
        self.index_path = self.root / "lesson_index.json"
        self.snapshots = self.root / "snapshots"

    def _read_jsonl(self, path: pathlib.Path, parser: Any) -> tuple[Any, ...]:
        if not path.exists():
            return ()
        rows: list[Any] = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                value = json.loads(line)
                _reject_credentials(value)
                rows.append(parser(value))
            except Exception as exc:
                raise ValueError(f"LESSON_STORE_CORRUPT:{path.name}:{number}:{type(exc).__name__}") from exc
        return tuple(rows)

    def events(self) -> tuple[LearningEvent, ...]:
        return self._read_jsonl(self.events_path, LearningEvent.from_dict)

    def revisions(self) -> tuple[LessonRecord, ...]:
        return self._read_jsonl(self.revisions_path, LessonRecord.from_dict)

    def current_lessons(self) -> tuple[LessonRecord, ...]:
        latest: dict[str, LessonRecord] = {}
        for item in self.revisions():
            previous = latest.get(item.lesson_id)
            if previous is not None and item.revision != previous.revision + 1:
                raise ValueError(f"LESSON_STORE_CORRUPT:non-contiguous revision:{item.lesson_id}")
            latest[item.lesson_id] = item
        return tuple(latest[key] for key in sorted(latest))

    def record_event(self, event: LearningEvent) -> None:
        existing = {item.event_id for item in self.events()}
        if event.event_id in existing:
            return
        self._append(self.events_path, event.as_dict())

    def append_revision(self, lesson: LessonRecord) -> None:
        latest = {item.lesson_id: item for item in self.current_lessons()}
        previous = latest.get(lesson.lesson_id)
        expected = 1 if previous is None else previous.revision + 1
        if lesson.revision != expected:
            if previous is not None and lesson.as_dict() == previous.as_dict():
                return
            raise ValueError(f"lesson revision must be append-only: expected {expected}")
        self._append(self.revisions_path, lesson.as_dict())
        latest[lesson.lesson_id] = lesson
        self._write_index(tuple(latest.values()))

    def _append(self, path: pathlib.Path, value: dict[str, Any]) -> None:
        _reject_credentials(value)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _write_index(self, lessons: Iterable[LessonRecord]) -> None:
        rows = sorted(({"lesson_id": item.lesson_id, "revision": item.revision, "status": item.status.value, "scope": item.scope.as_dict()} for item in lessons), key=lambda row: row["lesson_id"])
        value = {"kind": "LessonIndex", "schema_version": "1.0", "lessons": rows, "index_hash": canonical_hash(rows), "contains_credentials": False}
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".lesson-index-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, self.index_path)
        finally:
            pathlib.Path(temporary).unlink(missing_ok=True)

    def write_snapshot(self, context: LessonContext) -> pathlib.Path:
        self.snapshots.mkdir(parents=True, exist_ok=True)
        path = self.snapshots / (context.lesson_snapshot_hash.replace(":", "-") + ".json")
        if not path.exists():
            value = {"kind": "LessonSnapshot", "schema_version": "1.0", **context.as_dict(), "contains_credentials": False}
            _reject_credentials(value)
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path


class NoOpLessonReader:
    def query(self, query: LessonQuery) -> LessonContext:
        query_hash = canonical_hash(query.as_dict())
        return LessonContext((), (), (), (), canonical_hash({"query_hash": query_hash, "lessons": []}), 0, query_hash, utc_now())


class NoOpLessonRecorder:
    def record_event(self, event: LearningEvent) -> None:
        return None

    def finalize_run(self, run_id: str) -> tuple[LessonRecord, ...]:
        return ()

