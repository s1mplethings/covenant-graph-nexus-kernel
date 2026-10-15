from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import commercial_warning_policy


def test_critical_warning_blocks_pass_final() -> None:
    result = commercial_warning_policy.classify_final_warnings(["delivery_manifest missing"])

    assert result["status"] == "fail"
    assert result["metadata"]["pass_final_allowed"] is False
    assert result["metadata"]["classification"]["critical"]


def test_major_warning_allows_deliver_with_warnings_not_pass_final() -> None:
    result = commercial_warning_policy.classify_final_warnings(["video blocked but screenshot/test/final zip OK"])

    assert result["status"] == "warning"
    assert result["verdict"] == "DELIVER_WITH_WARNINGS"
    assert result["metadata"]["pass_final_allowed"] is False


def test_minor_warning_allows_pass_final() -> None:
    result = commercial_warning_policy.classify_final_warnings(["UI polish limited"])

    assert result["status"] == "pass"
    assert result["verdict"] == "PASS_FINAL"
    assert result["metadata"]["classification"]["minor"]
    assert result["metadata"]["pass_final_allowed"] is True


def test_ready_with_warnings_requires_warning_classification() -> None:
    result = commercial_warning_policy.require_warning_classification("ready_with_warnings", None)

    assert result["status"] == "fail"
    assert result["verdict"] == "ready_with_warnings_requires_warning_classification"
