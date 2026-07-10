from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_test_profile


def test_profile_marker_expressions_exclude_slow_provider_telegram_e2e() -> None:
    assert "slow" in run_test_profile.PROFILE_MARKS["quick"]
    assert "longrun" in run_test_profile.PROFILE_MARKS["quick"]
    assert "long_journey" in run_test_profile.PROFILE_MARKS["quick"]
    assert "provider" in run_test_profile.PROFILE_MARKS["quick"]
    assert "live_provider" in run_test_profile.PROFILE_MARKS["quick"]
    assert "telegram" in run_test_profile.PROFILE_MARKS["quick"]
    assert "e2e" in run_test_profile.PROFILE_MARKS["quick"]
    assert "benchmark" in run_test_profile.PROFILE_MARKS["quick"]
    assert run_test_profile.PROFILE_MARKS["longrun"] == "longrun or long_journey or benchmark"
    assert run_test_profile.PROFILE_MARKS["provider"] == "provider or live_provider"
    assert run_test_profile.PROFILE_PATHS["quick"] == ["tests", "scripts"]


def test_run_test_profile_writes_result_without_running_real_suite(monkeypatch, tmp_path: pathlib.Path) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="1 passed\n", stderr="")

    monkeypatch.setattr(run_test_profile.subprocess, "run", fake_run)
    result = run_test_profile.run_profile("quick", out_dir=tmp_path, timeout=10)

    assert result["status"] == "PASS"
    assert "-m not (slow or e2e or live_provider or telegram or benchmark or longrun or long_journey or provider)" in result["command"]
    assert (tmp_path / "quick_result.json").exists()
