from pathlib import Path

from scripts.import_historical_lessons import import_lessons

from cgkn.application.learning import FileLessonStore, LessonStatus, StoreLessonReader, LessonQuery


ROOT = Path(__file__).resolve().parents[3]


def test_import_is_structured_bounded_and_idempotent(tmp_path):
    first = import_lessons(ROOT, tmp_path / "artifacts", tmp_path / "receipt.json")
    second = import_lessons(ROOT, tmp_path / "artifacts", tmp_path / "receipt-2.json")
    store = FileLessonStore(tmp_path / "artifacts")
    assert first["validated_count"] == 4 and first["policy_count"] == 4
    assert len(store.current_lessons()) == 8
    assert not second["imported_lesson_ids"] and len(second["reused_lesson_ids"]) == 8


def test_imported_project_and_capability_lessons_are_queryable(tmp_path):
    import_lessons(ROOT, tmp_path, tmp_path / "receipt.json")
    reader = StoreLessonReader(FileLessonStore(tmp_path))
    project = reader.query(LessonQuery("project.codegen", "GENERATION", provider_id="grok", project_id="folder_manifest_cli"))
    capability = reader.query(LessonQuery("capability.build", "GENERATION", provider_id="grok", capability_ref="project.python.pyproject.render@1"))
    assert len(project.lesson_ids) >= 2
    assert len(capability.lesson_ids) >= 1

