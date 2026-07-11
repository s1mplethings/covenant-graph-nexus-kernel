from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import customer_status


def test_customer_status_hides_internal_gate_terms() -> None:
    rendered = customer_status.render_status("FAILED_WITH_RECOVERY_OPTIONS", details="FACT_BLOCKED gate traceback")

    text = rendered["message"]
    assert "FACT_BLOCKED" not in text
    assert "gate" not in text.lower()
    assert "traceback" not in text.lower()


def test_provider_quota_message_is_user_friendly() -> None:
    rendered = customer_status.render_from_internal({"status": "failed", "reason": "provider_quota"})

    assert rendered["public_status"] == "WAITING_FOR_PROVIDER_QUOTA"
    assert "模型额度不足" in rendered["message"]


def test_candidate_review_message_not_final_delivery() -> None:
    rendered = customer_status.render_status("READY_FOR_REVIEW")

    assert "候选项目" in rendered["message"]
    assert "最终项目包已准备好" not in rendered["message"]


def test_final_ready_requires_final_gate_pass() -> None:
    rendered = customer_status.render_status("FINAL_READY", final_gate_passed=False)

    assert rendered["public_status"] == "PACKAGING_FINAL"


def test_provider_quota_status_maps_to_waiting_for_provider_quota() -> None:
    rendered = customer_status.render_from_internal({"reason": "provider_quota"})

    assert rendered["public_status"] == "WAITING_FOR_PROVIDER_QUOTA"
    assert "模型额度不足" in rendered["message"]
