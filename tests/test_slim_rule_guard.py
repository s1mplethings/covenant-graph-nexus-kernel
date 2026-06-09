from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.cgnk_slim_rule_guard as guard


def _checks_by_name() -> dict[str, dict]:
    result = guard.run_checks(strict=False)
    return {check["name"]: check for check in result["checks"]}


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


def test_all_hard_checks_pass_on_repo() -> None:
    result = guard.run_checks(strict=False)
    failing = [check["name"] for check in result["checks"] if not check["ok"]]
    assert result["ok"], failing


def test_confirmation_forbids_run_local_pipeline() -> None:
    assert "run_local_pipeline" in guard.FORBIDDEN_CONFIRMATION_TERMS


def test_dispatch_driver_check_present_and_ok() -> None:
    checks = _checks_by_name()
    name = "default generation dispatch marks api_provider_project_generation driver"
    assert name in checks
    assert checks[name]["ok"]


def test_delivery_gate_and_emit_checks_present_and_ok() -> None:
    checks = _checks_by_name()
    for fn in ("send_delivery_from_manifest", "send_evidence_checkpoint"):
        name = f"{fn} delivers only through gate and emit"
        assert name in checks, name
        assert checks[name]["ok"], name


def test_legacy_wrapper_marker_checks_present_and_ok() -> None:
    checks = _checks_by_name()
    name = "legacy wrapper functions in the bridge are marked LEGACY ONLY"
    assert name in checks
    assert checks[name]["ok"]

