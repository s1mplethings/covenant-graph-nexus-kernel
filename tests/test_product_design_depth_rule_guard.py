from __future__ import annotations

from scripts import product_design_depth_rule_guard


def test_product_design_depth_rule_guard_passes() -> None:
    result = product_design_depth_rule_guard.inspect()
    assert result["status"] == "PASS", result["failures"]
    assert result["frozen_boundary_changes"] == []
    assert result["provider_calls"] == 0


def test_guard_covers_formal_mainline_and_maturity_separation() -> None:
    checks = product_design_depth_rule_guard.inspect()["checks"]
    assert checks["requirement_entry_freezes_contracts"]
    assert checks["postbuild_maturity_before_packager"]
    assert checks["public_gate_attaches_maturity"]
    assert checks["single_maturity_evaluator"]
    assert checks["independent_holdout_hash_is_bound"]
