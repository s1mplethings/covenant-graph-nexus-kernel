from __future__ import annotations

from cgkn.execution.contracts import utc_now

from .contracts import LessonContext, LessonQuery, LessonRecord, LessonStatus, canonical_hash
from .store import FileLessonStore


class StoreLessonReader:
    def __init__(self, store: FileLessonStore):
        self.store = store

    @staticmethod
    def _matches(lesson: LessonRecord, query: LessonQuery) -> bool:
        scope = lesson.scope
        pairs = (
            (scope.task_class, query.task_class), (scope.operation, query.operation),
            (scope.capability_ref, query.capability_ref), (scope.provider_id, query.provider_id),
            (scope.project_id, query.project_id),
        )
        return all(not expected or expected == actual for expected, actual in pairs)

    @staticmethod
    def _rank(lesson: LessonRecord, query: LessonQuery) -> int:
        scope = lesson.scope
        if scope.capability_ref == query.capability_ref and scope.capability_ref and scope.operation == query.operation:
            return 0
        if scope.task_class == query.task_class and scope.task_class and scope.operation == query.operation:
            return 1
        if scope.provider_id == query.provider_id and scope.provider_id and scope.task_class == query.task_class:
            return 2
        if scope.project_id == query.project_id and scope.project_id:
            return 3
        return 4

    def query(self, query: LessonQuery) -> LessonContext:
        eligible = [item for item in self.store.current_lessons() if item.status is LessonStatus.VALIDATED and self._matches(item, query)]
        eligible.sort(key=lambda item: (self._rank(item, query), -item.support_count, item.contradiction_count, -_timestamp_key(item.updated_at), item.lesson_id))
        selected: list[LessonRecord] = []
        chars = 0
        for item in eligible:
            size = len(item.guidance) + len(item.avoid)
            if len(selected) >= query.max_lessons or chars + size > query.max_chars:
                continue
            selected.append(item); chars += size
        query_hash = canonical_hash(query.as_dict())
        snapshot_payload = [{"lesson_id": item.lesson_id, "revision": item.revision, "guidance": item.guidance, "avoid": item.avoid} for item in selected]
        context = LessonContext(
            tuple(item.lesson_id for item in selected), tuple(item.revision for item in selected),
            tuple(item.guidance for item in selected), tuple(item.avoid for item in selected),
            canonical_hash({"query_hash": query_hash, "lessons": snapshot_payload}), chars, query_hash, utc_now(),
        )
        self.store.write_snapshot(context)
        return context


def _timestamp_key(value: str) -> int:
    digits = "".join(char for char in value if char.isdigit())[:20]
    return int(digits or 0)

