from __future__ import annotations

import copy
import pathlib
import sys


SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import baseline_ledger
import run_baseline_regression


def test_current_baseline_ledger_is_valid() -> None:
    assert baseline_ledger.load_and_validate()["status"] == "PASS"


def test_removed_guarantee_is_a_breaking_change() -> None:
    value = baseline_ledger.load_and_validate()
    assert value["status"] == "PASS"
    import json
    current = json.loads((baseline_ledger.ROOT / "governance/current_baseline.json").read_text(encoding="utf-8"))
    changed = copy.deepcopy(current)
    changed["removed_guarantees"] = ["kernel_foundation=COMPLETE"]
    changed["baseline_hash"] = baseline_ledger.canonical_hash(changed)
    assert "BREAKING_BASELINE_CHANGE" in baseline_ledger.validate_baseline(changed)


def test_fast_and_full_plans_preserve_required_layers() -> None:
    fast = run_baseline_regression.profile_commands("fast")
    rendered = [" ".join(command) for command in fast]
    for required in (
        "kernel_completeness_gate.py", "receipt_freshness.py", "--profile unit",
        "--profile boundary", "--profile fault", "--profile security",
        "--profile local-functional", "tests/application/software_project",
        "--profile schema", "--profile fake",
    ):
        assert any(required in command for command in rendered)
    assert len(run_baseline_regression.profile_commands("full")) > len(fast)
