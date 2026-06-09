from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_cgnk_slim_rule_guard_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/cgnk_slim_rule_guard.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[0] == "PASS"


def test_cgnk_slim_rule_guard_strict_reports_existing_bloat() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/cgnk_slim_rule_guard.py", "--strict"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "WARN:" in result.stdout
