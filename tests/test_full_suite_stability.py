from __future__ import annotations

import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import pytest_hang_diagnostics
import conftest


def test_pytest_hang_diagnostics_reports_timeout(monkeypatch) -> None:
    monkeypatch.setattr(pytest_hang_diagnostics, "collect_nodes", lambda _args=None: ["tests/fake_test.py::test_hangs"])

    def fake_run_node(node: str, *, timeout: int) -> dict:
        return {
            "nodeid": node,
            "status": "TIMEOUT",
            "returncode": None,
            "duration_seconds": timeout,
            "timeout_seconds": timeout,
        }

    monkeypatch.setattr(pytest_hang_diagnostics, "run_node", fake_run_node)

    result = pytest_hang_diagnostics.diagnose(per_test_timeout=3)

    assert result["status"] == "BLOCKED"
    assert result["blocked_test"]["nodeid"] == "tests/fake_test.py::test_hangs"
    assert result["blocked_test"]["index"] == 1


def test_pytest_hang_diagnostics_collects_current_suite() -> None:
    nodes = pytest_hang_diagnostics.collect_nodes(timeout=60)

    assert any("tests/test_full_suite_stability.py::test_pytest_hang_diagnostics_reports_timeout" in node for node in nodes)
    assert any("tests/test_reference_answer_project_trial.py" in node for node in nodes)


def test_pytest_progress_heartbeat_is_bounded_jsonl(tmp_path: pathlib.Path, monkeypatch) -> None:
    progress = tmp_path / "pytest_progress.jsonl"
    monkeypatch.setattr(conftest, "PROGRESS_PATH", progress)

    conftest._write_progress({"event": "test_start", "nodeid": "tests/example.py::test_one"})

    assert progress.exists()
    assert '"event": "test_start"' in progress.read_text(encoding="utf-8")


def test_pytest_external_plugins_are_disabled_by_config() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--version", "--version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0
    assert "registered third-party plugins" not in proc.stdout
