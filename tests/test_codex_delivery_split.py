from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.conversation_delivery import candidate_review_sender, final_delivery_sender, retry_recovery, status_renderer

pytestmark = [pytest.mark.codex]


def test_candidate_sender_cannot_mark_final_delivered() -> None:
    session = {"generation": {"candidate_review_sent": True, "final_delivered": True, "PASS_FINAL": True}}

    for key in candidate_review_sender.FORBIDDEN_FINAL_KEYS:
        session["generation"].pop(key, None)
    result = candidate_review_sender.assert_candidate_sender_scope(session)

    assert result["status"] == "pass"


def test_final_sender_requires_final_gate_pass() -> None:
    result = final_delivery_sender.send_final_delivery(None, "chat", pathlib.Path("."), {"generation": {}}, {"final_verdict": "DELIVER_WITH_WARNINGS", "delivery_allowed": False})

    assert result["status"] == "rejected"
    assert result["reason"] == "final_gate_not_passed"


def test_status_renderer_hides_internal_terms() -> None:
    rendered = status_renderer.render({"status": "FAILED_WITH_RECOVERY_OPTIONS", "message": "gate FACT_BLOCKED traceback"})

    assert "gate" not in rendered["message"].lower()
    assert "FACT_BLOCKED" not in rendered["message"]


def test_retry_recovery_handles_provider_quota() -> None:
    result = retry_recovery.recovery_options({"reason": "provider_quota"})

    assert result["status"] == "WAITING_FOR_PROVIDER_QUOTA"
    assert "模型额度不足" in result["message"]
