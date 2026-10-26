from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from cgkn.execution.contracts import utc_now

from .contracts import LearningEvent, LessonRecord, LessonScope, LessonStatus
from .store import FileLessonStore


_NON_PROMPT_DOMAINS = {
    "FRAMEWORK_HARNESS_DEFECT", "FRAMEWORK_VALIDATOR_DEFECT", "PROVIDER_TRANSPORT_FAILURE",
    "PROVIDER_TIMEOUT", "EXTERNAL_DEPENDENCY_FAILURE", "ENVIRONMENT_BLOCKED", "UNKNOWN_FAILURE",
}


class LessonExtractor:
    """Deterministic V0 extractor; it consumes terminal structured events only."""

    def extract(self, events: Iterable[LearningEvent]) -> tuple[LessonRecord, ...]:
        rows: list[LessonRecord] = []
        for event in events:
            if not event.failure_code or event.failure_code == "PASS" or event.final_outcome != "PASS":
                continue
            if event.failure_domain in _NON_PROMPT_DOMAINS:
                status = LessonStatus.PROMOTED_TO_POLICY if event.action_taken in {"REVALIDATE_EXISTING", "WAIT_EXTERNAL"} else LessonStatus.REVIEW
            elif not self._closed_single_change(event):
                status = LessonStatus.REVIEW
            else:
                status = LessonStatus.VALIDATED
            scope = LessonScope(event.task_class, event.operation, event.capability_ref, event.provider_id, "")
            guidance, avoid = self._guidance(event)
            lesson_id = LessonRecord.stable_id(scope, event.failure_code, "corrective-action", "prevent-recurrence")
            rows.append(LessonRecord(lesson_id, 1, status, scope, event.failure_code, guidance, avoid, event.evidence_refs, 0, 0, event.created_at, event.created_at))
        return tuple(rows)

    @staticmethod
    def _closed_single_change(event: LearningEvent) -> bool:
        return (
            event.failure_domain in {"CANDIDATE_DEFECT", "CANDIDATE_POLICY_DEFECT"}
            and event.action_taken == "REPAIR_CANDIDATE"
            and len(event.changed_authorities) == 1
            and event.changed_authorities[0] == "CANDIDATE_REVISION"
            and bool(event.candidate_revision_id)
        )

    @staticmethod
    def _guidance(event: LearningEvent) -> tuple[str, str]:
        code = event.failure_code.replace("_", " ").lower()
        return (f"For {event.operation.lower()}, prevent recurrence of {code} while preserving every authoritative contract.", f"Do not repeat {code} or modify validators, contracts, provider routing, or policy to hide it.")


class StoreLessonRecorder:
    def __init__(self, store: FileLessonStore, extractor: LessonExtractor | None = None):
        self.store, self.extractor = store, extractor or LessonExtractor()

    def record_event(self, event: LearningEvent) -> None:
        self.store.record_event(event)

    def finalize_run(self, run_id: str) -> tuple[LessonRecord, ...]:
        events = tuple(item for item in self.store.events() if item.run_id == run_id)
        created: list[LessonRecord] = []
        existing = {item.lesson_id: item for item in self.store.current_lessons()}
        for lesson in self.extractor.extract(events):
            if lesson.lesson_id in existing:
                continue
            self.store.append_revision(lesson); created.append(lesson)
        return tuple(created)


def record_feedback(store: FileLessonStore, lesson_ids: Iterable[str], *, success: bool, same_trigger_failure: bool = False) -> tuple[LessonRecord, ...]:
    current = {item.lesson_id: item for item in store.current_lessons()}
    revisions: list[LessonRecord] = []
    for lesson_id in lesson_ids:
        item = current.get(lesson_id)
        if item is None:
            continue
        contradiction = item.contradiction_count + int(same_trigger_failure)
        status = LessonStatus.REVIEW if contradiction >= 2 else item.status
        revised = replace(item, revision=item.revision + 1, status=status, support_count=item.support_count + int(success), contradiction_count=contradiction, updated_at=utc_now(), supersedes=f"{item.lesson_id}@{item.revision}")
        store.append_revision(revised); revisions.append(revised)
    return tuple(revisions)

