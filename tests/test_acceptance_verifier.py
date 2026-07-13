from __future__ import annotations

import pathlib
import re

from scripts.acceptance_verifier import REQUIRED_GATES, canonical_verdict, write_canonical_verdict


def _all_pass() -> dict[str, str]:
    return {gate: "PASS" for gate in REQUIRED_GATES}


def test_only_all_required_pass_can_return_pass() -> None:
    assert canonical_verdict(_all_pass())["overall_readiness"] == "PASS"

    for gate, status in (
        ("recovery", "NOT_EVALUATED"),
        ("package", "PASS_WITH_LIMITS"),
        ("leaf_behavior_tests", "NEEDS_REWORK"),
        ("provider_consumption", "BLOCKED_PROVIDER"),
        ("user_review", "FAIL"),
    ):
        inputs = _all_pass()
        inputs[gate] = status
        assert canonical_verdict(inputs)["overall_readiness"] != "PASS"


def test_package_warning_propagates_to_pass_with_limits() -> None:
    inputs = _all_pass()
    inputs["package_manifest"] = {"status": "ready_with_warnings"}

    verdict = canonical_verdict(inputs)

    assert verdict["upstream_statuses"]["package"] == "PASS_WITH_LIMITS"
    assert verdict["overall_readiness"] == "PASS_WITH_LIMITS"


def test_required_stage_not_evaluated_is_needs_rework_not_pass() -> None:
    inputs = _all_pass()
    inputs["recovery"] = "NOT_EVALUATED"
    inputs["runner_verdict"] = "PASS"

    verdict = canonical_verdict(inputs)

    assert verdict["overall_readiness"] == "NEEDS_REWORK"
    assert verdict["conflicts"] == [{"source": "runner_verdict", "claimed": "PASS", "canonical": "NEEDS_REWORK"}]


def test_gui_screenshot_and_user_review_require_real_completion() -> None:
    inputs = _all_pass()
    inputs.update({"gui_project": True, "screenshots_present": False, "user_review_required": True, "user_review_completed": False})

    verdict = canonical_verdict(inputs)

    assert verdict["overall_readiness"] == "NEEDS_REWORK"
    assert verdict["upstream_statuses"]["screenshots"] == "NEEDS_REWORK"
    assert verdict["upstream_statuses"]["user_review"] == "NEEDS_REWORK"


def test_write_canonical_verdict_only_writes_final_verdict(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "final_verdict.json"

    verdict = write_canonical_verdict(target, _all_pass())

    assert verdict["overall_readiness"] == "PASS"
    assert target.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["final_verdict.json"]


def test_production_final_verdict_writes_go_through_canonical_writer() -> None:
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    direct_write = re.compile(r"(write_json|write_text|open)\([^\n]*final_verdict\.json")
    for path in sorted((root / "scripts").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        if direct_write.search(text):
            offenders.append(rel)
        if "final_verdict.json" in text and "write_canonical_verdict" in text:
            continue
    assert offenders == []
