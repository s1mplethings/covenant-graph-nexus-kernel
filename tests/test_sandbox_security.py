from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import sandbox_security


def test_sandbox_rejects_dangerous_npm_script() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir)
        (project / "package.json").write_text(json.dumps({"scripts": {"postinstall": "rm -rf .."}}), encoding="utf-8")
        report = sandbox_security.scan_project(project)

    assert report["status"] == "fail"
    assert report["verdict"] == "SECURITY_BLOCKED"
    assert any(item["risk"] == "rm -rf" for item in report["dangerous_commands"])


def test_sandbox_rejects_write_outside_candidate_dir() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        candidate = root / "candidate"
        outside = root / "outside" / "file.txt"
        candidate.mkdir()
        outside.parent.mkdir()
        outside.write_text("x", encoding="utf-8")

        result = sandbox_security.validate_execution_path(outside, [candidate])

    assert result["status"] == "fail"
    assert "path_outside_allowed_roots" == result["verdict"]


def test_sandbox_redacts_provider_api_key_from_runtime_env() -> None:
    runtime = sandbox_security.safe_runtime_env({"PATH": "bin", "OPENAI_API_KEY": "sk-test", "CUSTOM_TOKEN": "secret"})

    assert runtime == {"PATH": "bin"}


def test_security_block_prevents_final_promotion() -> None:
    report = {"status": "fail", "verdict": "SECURITY_BLOCKED"}
    result = sandbox_security.assert_final_promotion_allowed(report)

    assert result["status"] == "fail"
    assert "security_blocked" in result["blockers"]
