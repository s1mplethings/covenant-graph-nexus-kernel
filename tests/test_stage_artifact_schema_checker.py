from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import stage_artifact_schema_checker


def test_stage_artifact_schema_checker_passes_complete_artifact(tmp_path: pathlib.Path) -> None:
    artifact = {
        "stage": "ingest_video",
        "status": "degraded",
        "count": 1,
        "input_path": "input.mp4",
        "output_path": "media_manifest.json",
        "created_at": "2026-06-19T00:00:00Z",
        "upstream_artifacts": [],
        "items": [{"path": "input.mp4"}],
    }
    (tmp_path / "media_manifest.json").write_text(json.dumps(artifact), encoding="utf-8")
    result = stage_artifact_schema_checker.check(tmp_path, ["media_manifest.json"])
    assert result["status"] == "PASS"


def test_stage_artifact_schema_checker_fails_missing_schema_fields(tmp_path: pathlib.Path) -> None:
    (tmp_path / "media_manifest.json").write_text(json.dumps({"stage": "ingest_video"}), encoding="utf-8")
    result = stage_artifact_schema_checker.check(tmp_path, ["media_manifest.json"])
    assert result["status"] == "FAIL"
    assert "stage_artifact_schema_invalid:media_manifest.json" in result["blockers"]
