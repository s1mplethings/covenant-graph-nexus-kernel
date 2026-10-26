from pathlib import Path

from scripts.lesson_generation_architecture_gate import check


ROOT = Path(__file__).resolve().parents[3]


def test_all_production_generation_uses_lesson_context():
    assert check(ROOT)["status"] == "PASS"


def test_benchmark_is_explicitly_disabled_by_policy():
    source = (ROOT / "cgkn/application/provider_evaluation/service.py").read_text(encoding="utf-8")
    assert 'lesson_policy="DISABLED_BY_POLICY"' in source


def test_lessons_cannot_mutate_candidate_or_action_policy():
    learning = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "cgkn/application/learning").glob("*.py"))
    assert "CandidateRevisionStore" not in learning
    assert "CapabilityBuildActionPolicy" not in learning


def test_delivery_uses_only_local_packager():
    source = (ROOT / "cgkn/application/project_production/service.py").read_text(encoding="utf-8")
    assert "local_packager.package_project" in source
    assert "zipfile.ZipFile(package)" in source
    assert ".write(package" not in source

