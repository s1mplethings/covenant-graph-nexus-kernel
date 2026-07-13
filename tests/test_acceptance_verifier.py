from __future__ import annotations

import pathlib

from scripts.acceptance_verifier import REQUIRED_GATES, canonical_verdict, write_canonical_verdict


def _all_pass() -> dict[str, str]:
    return {gate: "PASS" for gate in REQUIRED_GATES}


def test_only_all_required_pass_can_return_pass() -> None:
    assert canonical_verdict(_all_pass())["overall_readiness"] == "PASS"

    for gate, status in (
        ("recovery", "NOT_EVALUATED"),
        ("package", "PASS_WITH_LIMITS"),
        ("tests", "NEEDS_REWORK"),
        ("provider", "BLOCKED_PROVIDER"),
        ("review", "FAIL"),
    ):
        inputs = _all_pass()
        inputs[gate if gate in inputs else "tests"] = status
        assert canonical_verdict(inputs)["overall_readiness"] != "PASS"


def test_package_warning_propagates_to_pass_with_limits() -> None:
    inputs = _all_pass()
    inputs["package_manifest"] = {"status": "ready_with_warnings"}

    verdict = canonical_verdict(inputs)

    assert verdict["upstream_statuses"]["package"] == "PASS_WITH_LIMITS"
    assert verdict["overall_readiness"] == "PASS_WITH_LIMITS"


def test_write_canonical_verdict_only_writes_final_verdict(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "final_verdict.json"

    verdict = write_canonical_verdict(target, _all_pass())

    assert verdict["overall_readiness"] == "PASS"
    assert target.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["final_verdict.json"]
