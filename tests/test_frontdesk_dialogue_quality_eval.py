from __future__ import annotations

import importlib.util
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
EVAL = ROOT / "generated" / "front_back_separate_eval" / "run_front_back_eval.py"


def _load_eval_module():
    spec = importlib.util.spec_from_file_location("front_back_eval", EVAL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frontdesk_dialogue_quality_eval() -> None:
    module = _load_eval_module()
    result = module.run_frontdesk_eval()

    assert result["overall_average"] >= 22
    assert result["leaks"] == []
    assert result["fake_completions"] == []
    assert {item["chat_id"] for item in result["start_calls"]} >= {"frontdesk-a", "frontdesk-b", "frontdesk-c"}
    rows = result["rows"]
    assert any(row["dialogue"] == "A" and row["turn"] == 1 and row["start_generation_called"] is False for row in rows)
    assert any(row["dialogue"] == "B" and row["whiteboard.target_project_architecture"].get("model_mode") == "local_model" for row in rows)
    assert any(
        row["dialogue"] == "C"
        and row["turn"] == 5
        and row["active_run.status"] in {"delivered", "revision_requested", "next_revision_waiting_confirmation"}
        for row in rows
    )
