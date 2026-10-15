from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import agent_state_observer, formal_model_contract


def test_agent_state_observer_reads_run_dir_state(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    candidate = run_dir / "candidate_project"
    final = run_dir / "final_project"
    artifacts = run_dir / "artifacts"
    candidate.mkdir(parents=True)
    final.mkdir(parents=True)
    artifacts.mkdir(parents=True)

    (run_dir / "project_spec.json").write_text('{"goal":"task board"}\n', encoding="utf-8")
    (candidate / "acceptance_matrix.json").write_text('{"features":["task board"]}\n', encoding="utf-8")
    (artifacts / "semantic_review_result.json").write_text('{"status":"pass"}\n', encoding="utf-8")
    shot = artifacts / "screenshots" / "app_screenshot.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"image")
    bundle = final / "final_project_bundle.zip"
    bundle.write_bytes(b"zip")
    (final / "delivery_manifest.json").write_text(
        json.dumps(
            {
                "package_path": str(bundle),
                "screenshot_path": str(shot),
                "public_final_gate": {"delivery_allowed": True, "missing": []},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (artifacts / "commercial_readiness_report.json").write_text('{"commercial_status":"COMMERCIAL_READY"}\n', encoding="utf-8")
    (artifacts / "provider_fallback_evidence.json").write_text(
        '{"requires_reverify":true,"reverify_attempted":true,"reverify_status":"pass"}\n',
        encoding="utf-8",
    )
    formal_model_contract.append_model_call(
        run_dir,
        stage="generation",
        provider="local_model_router",
        model="test-model",
        requested=True,
        executed=True,
        status="ok",
        used_in_formal_chain=True,
        input_value="goal",
        output_value="candidate",
    )

    state = agent_state_observer.observe_run_state(run_dir)

    assert state["has_project_spec"] is True
    assert state["has_acceptance_matrix"] is True
    assert state["candidate_exists"] is True
    assert state["semantic_review_status"] == "pass"
    assert state["final_project_exists"] is True
    assert state["delivery_manifest_exists"] is True
    assert state["final_bundle_exists"] is True
    assert state["screenshot_evidence_exists"] is True
    assert state["public_gate_status"] == "READY"
    assert state["commercial_status"] == "COMMERCIAL_READY"
    assert state["model_participation_status"] == "pass"
    assert state["fallback_reverify_status"] == "pass"
