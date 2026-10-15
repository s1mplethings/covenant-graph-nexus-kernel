from __future__ import annotations

import json
import multiprocessing as mp
import os
import pathlib
import queue
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import customer_agent_scorecard
import customer_agent_simulator
import run_customer_agent_long_journey_trial as journey

pytestmark = [pytest.mark.longrun, pytest.mark.long_journey, pytest.mark.slow, pytest.mark.e2e]


def _trial_worker(queue: mp.Queue, kwargs: dict) -> None:
    try:
        result = journey.run_trial(**kwargs)
        queue.put({"ok": True, "result": result})
    except BaseException as exc:  # pragma: no cover - worker diagnostics
        queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def run_tmp_trial(
    tmp_path: pathlib.Path,
    *,
    capture_screenshot: bool = True,
    enable_rework: bool = True,
    use_reference: bool = True,
) -> dict:
    timeout = int(os.environ.get("CGKN_LONG_JOURNEY_TEST_TIMEOUT", "90"))
    kwargs = {
        "root": tmp_path,
        "no_live": True,
        "use_reference_answer_trial": use_reference,
        "enable_rework": enable_rework,
        "capture_screenshot": capture_screenshot,
    }
    result_queue: mp.Queue = mp.Queue()
    proc = mp.Process(target=_trial_worker, args=(result_queue, kwargs))
    proc.start()
    try:
        payload = result_queue.get(timeout=timeout)
    except queue.Empty:
        proc.terminate()
        proc.join(10)
        diagnosis = {
            "status": "timeout",
            "timeout_seconds": timeout,
            "capture_screenshot": capture_screenshot,
            "enable_rework": enable_rework,
            "use_reference": use_reference,
        }
        (tmp_path / "long_journey_timeout_diagnosis.json").write_text(json.dumps(diagnosis, ensure_ascii=False, indent=2), encoding="utf-8")
        pytest.fail(f"long journey trial exceeded {timeout}s; diagnosis written to {tmp_path / 'long_journey_timeout_diagnosis.json'}")
    proc.join(10)
    if proc.is_alive():
        proc.terminate()
        proc.join(10)
    if not payload.get("ok"):
        pytest.fail(str(payload.get("error", "long journey worker failed")))
    return payload["result"]


def test_trial_contains_required_long_journey_events(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    events = {entry["event"] for entry in result["dialogue"]}

    assert result["customer_journey_event_count"] >= 25
    assert set(customer_agent_simulator.REQUIRED_JOURNEY_EVENTS).issubset(events)


def test_customer_agent_permissions_are_black_box(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    controls = result["customer_agent_controls"]
    rework = result["rework_report"]

    assert controls["can_modify_cgkn_code"] is False
    assert controls["can_generate_target_project_code"] is False
    assert controls["can_forge_artifacts"] is False
    assert controls["code_write_attempted"] is False
    assert rework["customer_agent_modified_cgkn_code"] is False
    assert rework["customer_agent_generated_target_project_code"] is False


def test_customer_agent_does_not_forge_artifacts(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    scorecard = result["scorecard"]
    project_dir = pathlib.Path(result["generated_project_path"])

    assert result["customer_agent_controls"]["artifact_forgery_attempted"] is False
    assert scorecard["delivery_evidence"]["zip_ok"] is False
    assert not (project_dir / "final_project_bundle.zip").exists()
    assert scorecard["delivery_evidence"]["screenshot_ok"] is True
    assert pathlib.Path(scorecard["delivery_evidence"]["smoke_log"]).exists()


def test_customer_challenges_and_rework_request_are_present(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    dialogue = result["dialogue"]
    challenges = [entry for entry in dialogue if entry["actor"] == "customer" and "challenge" in entry["event"]]
    rework = [entry for entry in dialogue if entry["event"] == "customer_requests_rework"]

    assert len(challenges) >= 3
    assert len(rework) >= 1
    assert "README" in rework[0]["message"]


def test_outputs_dialogue_and_scorecard_artifacts(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    dialogue_path = pathlib.Path(result["artifact_paths"]["dialogue"])
    scorecard_path = pathlib.Path(result["artifact_paths"]["scorecard"])

    assert dialogue_path.exists()
    rows = [json.loads(line) for line in dialogue_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows
    for row in rows:
        assert {"turn", "actor", "event", "message", "evidence_refs", "customer_satisfaction_delta", "known_gaps"}.issubset(row)
    assert scorecard_path.exists()
    assert json.loads(scorecard_path.read_text(encoding="utf-8"))["total"] == result["scorecard"]["total"]


def test_requirement_delivery_and_capability_evidence_are_checked(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    scorecard = result["scorecard"]

    assert scorecard["requirement_evidence"]["status"] == "PASS"
    assert not scorecard["requirement_evidence"]["missing"]
    assert scorecard["product_contract_evidence"]["status"] == "PASS"
    assert scorecard["implementation_evidence"]["status"] == "PASS"
    assert scorecard["delivery_evidence"]["status"] == "FAIL"
    assert scorecard["capability_evidence"]["status"] == "PASS"


def test_customer_acceptance_is_distinct_from_commercial_ready(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    scorecard = result["scorecard"]

    assert scorecard["verdict"] == "NEEDS_REWORK"
    assert scorecard["commercial_readiness"]["commercial_ready"] is False
    assert result["customer_acceptance_equals_commercial_ready"] is False


def test_customer_acceptance_does_not_auto_set_commercial_ready(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)

    assert result["scorecard"]["total"] >= 75
    assert result["commercial_readiness"]["commercial_ready"] is False
    assert result["capability_manifest"]["commercial_ready"] is False


def test_degraded_placeholder_fixture_contract_only_status_is_customer_visible(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    capability = result["scorecard"]["capability_evidence"]

    assert capability["degraded_capabilities_customer_visible"] is True
    assert any(token in capability["visible_degraded_tokens"] for token in {"degraded", "fixture", "contract_fixture", "placeholder"})
    assert capability["production_asr_claimed"] is False


def test_missing_screenshot_prevents_customer_accepted(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path, capture_screenshot=False)

    assert result["scorecard"]["delivery_evidence"]["screenshot_ok"] is False
    assert result["scorecard"]["verdict"] != "CUSTOMER_ACCEPTED"


def test_missing_zip_prevents_customer_accepted(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    project_dir = pathlib.Path(result["generated_project_path"])
    assert not (project_dir / "final_project_bundle.zip").exists()

    dialogue = customer_agent_simulator.build_dialogue(result, rework_completed=True)
    rescored = customer_agent_scorecard.score_customer_journey(
        trial_result=result,
        dialogue=dialogue,
        rework_completed=True,
    )
    assert rescored["delivery_evidence"]["zip_ok"] is False
    assert rescored["verdict"] != "CUSTOMER_ACCEPTED"


def test_missing_test_report_or_delivery_notes_deducts_score(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    project_dir = pathlib.Path(result["generated_project_path"])
    (project_dir / "TEST_REPORT.md").unlink()

    rescored = customer_agent_scorecard.score_customer_journey(
        trial_result=result,
        dialogue=result["dialogue"],
        rework_completed=True,
    )
    assert "TEST_REPORT.md_missing" in rescored["blockers"]

    (project_dir / "DELIVERY_NOTES.md").unlink()
    rescored_again = customer_agent_scorecard.score_customer_journey(
        trial_result=result,
        dialogue=result["dialogue"],
        rework_completed=True,
    )
    assert "DELIVERY_NOTES.md_missing" in rescored_again["blockers"]


def test_rework_report_is_updated_after_rework(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path, enable_rework=True)
    report = result["rework_report"]
    report_path = pathlib.Path(result["artifact_paths"]["rework_report"])

    assert report["status"] == "FAIL"
    assert report_path.exists()
    assert "README" in report["request"]
    assert any(path.endswith("README.md") for path in report["updated_files"])


def test_reference_name_leak_passes(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)

    assert result["reference_name_leak_status"] == "PASS"
    assert "CGKN" in pathlib.Path(result["artifact_paths"]["summary"]).read_text(encoding="utf-8")


def test_runner_cli_completes(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path, use_reference=False)

    assert result["scorecard"]["verdict"] == "NEEDS_REWORK"
    assert pathlib.Path(result["artifact_paths"]["trial"]).exists()
