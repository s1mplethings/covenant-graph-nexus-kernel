from __future__ import annotations

import pathlib
import zipfile

from scripts.full_dynamic_project_resume_trace_bundle import REQUIRED, create_resume_trace_bundle


def test_resume_trace_requires_and_bundles_all_sections(tmp_path: pathlib.Path) -> None:
    for item in REQUIRED:
        path = tmp_path / item
        if "." in pathlib.Path(item).name:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        else:
            path.mkdir(parents=True, exist_ok=True)
            (path / "evidence.json").write_text("{}\n", encoding="utf-8")

    result = create_resume_trace_bundle(tmp_path)

    assert result["verdict"] == "PASS"
    with zipfile.ZipFile(result["path"]) as archive:
        names = set(archive.namelist())
    assert "00_INDEX.md" in names
    assert "leaf_resume/evidence.json" in names
    assert "resume_merge/evidence.json" in names
    assert "failure_injection/evidence.json" in names


def test_resume_trace_reports_missing_evidence(tmp_path: pathlib.Path) -> None:
    result = create_resume_trace_bundle(tmp_path)

    assert result["verdict"] == "FAIL"
    assert result["classification"] == "trace_incomplete"
