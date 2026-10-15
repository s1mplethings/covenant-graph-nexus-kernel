from __future__ import annotations

import pathlib

from benchmarks.project_generation_v1 import independent_evaluator


def test_dependency_free_project_needs_no_registry_or_wheelhouse(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
    result = independent_evaluator.prepare_clean_environment(
        project, tmp_path / "venv", {"mode": "wheelhouse", "wheelhouse": ""}
    )
    assert result["status"] == "PASS"
    assert result["dependency_source"] == "none_required"
    assert result["provider_network"] == "separate"


def test_missing_wheelhouse_fails_policy_before_install(tmp_path: pathlib.Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "requirements.txt").write_text("example-package==1.0\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(independent_evaluator, "_run", lambda *args, **kwargs: calls.append(args) or {"status": "PASS"})
    result = independent_evaluator.prepare_clean_environment(
        project, tmp_path / "venv", {"mode": "wheelhouse", "wheelhouse": str(tmp_path / "missing")}
    )
    assert result["status"] == "FAIL"
    assert result["stage"] == "dependency_policy"
    assert calls == []


def test_registry_requires_explicit_approval_before_install(tmp_path: pathlib.Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "requirements.txt").write_text("example-package==1.0\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(independent_evaluator, "_run", lambda *args, **kwargs: calls.append(args) or {"status": "PASS"})
    result = independent_evaluator.prepare_clean_environment(
        project, tmp_path / "venv", {"mode": "registry", "registry_approved": False}
    )
    assert result["status"] == "FAIL"
    assert result["package_registry_network"] is False
    assert calls == []
