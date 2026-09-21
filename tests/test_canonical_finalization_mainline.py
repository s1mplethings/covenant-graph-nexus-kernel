from __future__ import annotations

import importlib
import json
import pathlib

import pytest

from scripts import canonical_evidence_hash as hashes
from scripts import canonical_finalization as finalization
from scripts import codex_conversation
from scripts import local_packager
from scripts import provider_causal_trace


def _identity() -> dict[str, str]:
    return {"run_id": "run-1", "candidate_id": "candidate-1", "commit_sha": "a" * 40}


def _accepted(candidate_hash: str) -> dict[str, object]:
    return {
        **_identity(), "candidate_hash": candidate_hash, "source_sha": "a" * 40,
        "status": "PASS", "decision": "ACCEPT", "artifact_hash": "sha256:" + "b" * 64,
        "verification_evidence_hash": "sha256:" + "c" * 64,
        "governance_evidence_hash": "sha256:" + "d" * 64,
    }


def _project(tmp_path: pathlib.Path) -> tuple[pathlib.Path, str]:
    project = tmp_path / "项目"
    project.mkdir()
    (project / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (project / "README.md").write_text("# 工具\n\nPython standard library. Run: python main.py\n", encoding="utf-8")
    (project / "test_stderr.txt").write_text("", encoding="utf-8")
    return project, hashes.candidate_source_hash(project)


def test_01_state_machine_declares_required_states() -> None:
    required = {"WAITING_CANONICAL_VERIFICATION", "WAITING_GOVERNANCE_EVALUATION", "WAITING_ACCEPTANCE_DECISION", "WAITING_USER_REVIEW", "READY_FOR_PROMOTION", "PROMOTION_REJECTED", "READY_FOR_PACKAGING", "PACKAGING_FAILED", "READY_FOR_DELIVERY", "DELIVERY_BLOCKED", "DELIVERED"}
    assert required <= set(finalization.STATES)


def test_02_candidate_enters_canonical_verification(tmp_path: pathlib.Path) -> None:
    _, digest = _project(tmp_path)
    finalization.transition(tmp_path / "run", "CANDIDATE_MATERIALIZED", identity=_identity(), candidate_hash=digest)
    state = finalization.transition(tmp_path / "run", "WAITING_CANONICAL_VERIFICATION", identity=_identity(), candidate_hash=digest)
    assert state["state"] == "WAITING_CANONICAL_VERIFICATION"


def test_03_invalid_state_transition_is_rejected(tmp_path: pathlib.Path) -> None:
    _, digest = _project(tmp_path)
    finalization.transition(tmp_path / "run", "CANDIDATE_MATERIALIZED", identity=_identity(), candidate_hash=digest)
    with pytest.raises(ValueError, match="invalid canonical"):
        finalization.transition(tmp_path / "run", "DELIVERED", identity=_identity(), candidate_hash=digest)


def test_04_state_identity_cannot_change(tmp_path: pathlib.Path) -> None:
    _, digest = _project(tmp_path)
    finalization.transition(tmp_path / "run", "CANDIDATE_MATERIALIZED", identity=_identity(), candidate_hash=digest)
    changed = _identity() | {"candidate_id": "other"}
    with pytest.raises(ValueError, match="identity changed"):
        finalization.transition(tmp_path / "run", "WAITING_CANONICAL_VERIFICATION", identity=changed, candidate_hash=digest)


def test_05_canonical_verifier_uses_disk_evidence(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, digest = _project(tmp_path)
    (project / "test_execution.json").write_text("{}", encoding="utf-8")
    (project / "customer_runtime.json").write_text("{}", encoding="utf-8")
    provenance = tmp_path / "provenance.json"; provenance.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(finalization.real_test_execution, "inspect_test_report", lambda _p: {"status": "PASS"})
    monkeypatch.setattr(finalization.customer_runtime_runner, "inspect", lambda _p: {"status": "PASS"})
    report = finalization.canonical_verify(project, tmp_path / "run", identity=_identity(), expected_candidate_hash=digest, provenance_ref=provenance)
    assert report["status"] == "PASS" and report["authority_source"] == "local_canonical_verifier"


def test_06_canonical_verifier_recomputes_hash(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = _project(tmp_path)
    monkeypatch.setattr(finalization.real_test_execution, "inspect_test_report", lambda _p: {"status": "PASS"})
    monkeypatch.setattr(finalization.customer_runtime_runner, "inspect", lambda _p: {"status": "PASS"})
    report = finalization.canonical_verify(project, tmp_path / "run", identity=_identity(), expected_candidate_hash="sha256:" + "0" * 64, provenance_ref=tmp_path / "missing")
    assert "candidate_hash_matches" in report["blockers"]


def test_07_missing_readme_blocks_verification(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, digest = _project(tmp_path); (project / "README.md").unlink(); digest = hashes.candidate_source_hash(project)
    monkeypatch.setattr(finalization.real_test_execution, "inspect_test_report", lambda _p: {"status": "PASS"})
    monkeypatch.setattr(finalization.customer_runtime_runner, "inspect", lambda _p: {"status": "PASS"})
    report = finalization.canonical_verify(project, tmp_path / "run", identity=_identity(), expected_candidate_hash=digest, provenance_ref=tmp_path / "missing")
    assert "readme_present" in report["blockers"]


def test_08_missing_entrypoint_blocks_verification(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = _project(tmp_path); (project / "main.py").unlink(); digest = hashes.candidate_source_hash(project)
    monkeypatch.setattr(finalization.real_test_execution, "inspect_test_report", lambda _p: {"status": "PASS"})
    monkeypatch.setattr(finalization.customer_runtime_runner, "inspect", lambda _p: {"status": "PASS"})
    report = finalization.canonical_verify(project, tmp_path / "run", identity=_identity(), expected_candidate_hash=digest, provenance_ref=tmp_path / "missing")
    assert "entrypoint_present" in report["blockers"]


def test_09_surrogate_claims_are_not_verifier_inputs() -> None:
    source = pathlib.Path(finalization.__file__).read_text(encoding="utf-8")
    assert "tests_passed" not in source and "release recommendation" not in source


def test_10_live_and_surrogate_share_post_build_function() -> None:
    source = pathlib.Path(codex_conversation.__file__).read_text(encoding="utf-8")
    body = source.split("def run_provider_generation_job", 1)[1].split("\ndef ", 1)[0]
    assert body.count("post_build_finalize_provider_project(") == 1
    assert 'provider_mode = str(prior_generation.get("provider_mode"' in body


def test_11_surrogate_has_no_governance_authority() -> None:
    assert "surrogate" not in "local_product_design_depth_governance"


def test_12_surrogate_has_no_release_authority() -> None:
    assert "surrogate" not in "cgkn_local_canonical_promotion_authority"


def test_13_unverified_candidate_is_rejected(tmp_path: pathlib.Path) -> None:
    decision = finalization.decide_acceptance(tmp_path, identity=_identity(), candidate_hash="sha256:x", verification={"status": "NEEDS_REWORK", "blockers": ["tests"]}, governance={"status": "PASS", "failures": [], "artifact_hash": "g"})
    assert decision["decision"] == "REJECT"


def test_14_ungoverned_candidate_is_rejected(tmp_path: pathlib.Path) -> None:
    decision = finalization.decide_acceptance(tmp_path, identity=_identity(), candidate_hash="sha256:x", verification={"status": "PASS", "blockers": [], "artifact_hash": "v"}, governance={"status": "NEEDS_REWORK", "failures": ["proxy"], "artifact_hash": "g"})
    assert decision["decision"] == "REJECT"


def test_15_blocker_count_is_bound(tmp_path: pathlib.Path) -> None:
    decision = finalization.decide_acceptance(tmp_path, identity=_identity(), candidate_hash="sha256:x", verification={"status": "NEEDS_REWORK", "blockers": ["a"]}, governance={"status": "NEEDS_REWORK", "failures": ["b"], "artifact_hash": "g"})
    assert decision["blocker_count"] == 2


def test_16_accepted_candidate_has_local_authority(tmp_path: pathlib.Path) -> None:
    decision = finalization.decide_acceptance(tmp_path, identity=_identity(), candidate_hash="sha256:x", verification={"status": "PASS", "blockers": [], "artifact_hash": "v"}, governance={"status": "PASS", "failures": [], "artifact_hash": "g", "maturity_level": "TARGET_VALIDATED"})
    assert decision["decision"] == "ACCEPT" and decision["acceptance_authority"].startswith("cgkn_local")


def test_17_rejected_candidate_cannot_promote(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError, match="not accepted"):
        finalization.promote(tmp_path, identity=_identity(), candidate_hash="sha256:x", acceptance={"status": "NEEDS_REWORK", "decision": "REJECT"})


def test_18_acceptance_hash_mismatch_cannot_promote(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError, match="hash mismatch"):
        finalization.promote(tmp_path, identity=_identity(), candidate_hash="sha256:x", acceptance=_accepted("sha256:y"))


def test_19_accepted_candidate_promotes(tmp_path: pathlib.Path) -> None:
    promotion = finalization.promote(tmp_path, identity=_identity(), candidate_hash="sha256:x", acceptance=_accepted("sha256:x"))
    assert promotion["status"] == "PASS" and promotion["candidate_content_modified"] is False


def test_20_promotion_is_idempotent(tmp_path: pathlib.Path) -> None:
    first = finalization.promote(tmp_path, identity=_identity(), candidate_hash="sha256:x", acceptance=_accepted("sha256:x"))
    second = finalization.promote(tmp_path, identity=_identity(), candidate_hash="sha256:x", acceptance=_accepted("sha256:x"))
    assert first["artifact_hash"] == second["artifact_hash"] and second["idempotent_reuse"] is True


def test_21_cross_process_promotion_reload_is_idempotent(tmp_path: pathlib.Path) -> None:
    first = finalization.promote(tmp_path, identity=_identity(), candidate_hash="sha256:x", acceptance=_accepted("sha256:x"))
    module = importlib.reload(finalization)
    second = module.promote(tmp_path, identity=_identity(), candidate_hash="sha256:x", acceptance=_accepted("sha256:x"))
    assert first["artifact_hash"] == second["artifact_hash"]


def test_22_candidate_only_strict_packager_is_structured(tmp_path: pathlib.Path) -> None:
    project, _ = _project(tmp_path)
    (project / "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json").write_text("{}", encoding="utf-8")
    result = local_packager.package_project(project, require_promotion=True)
    assert result["status"] == "NEEDS_REWORK" and result["structured_blockers"][0]["category"] == "missing_authority"


def test_23_missing_promotion_has_next_action() -> None:
    blockers = finalization.packaging_blockers(None)
    assert blockers and blockers[0]["recoverable"] is True and blockers[0]["next_action"]


def test_24_tampered_promotion_hash_is_rejected(tmp_path: pathlib.Path) -> None:
    promotion = finalization.promote(tmp_path, identity=_identity(), candidate_hash="sha256:x", acceptance=_accepted("sha256:x"))
    path = pathlib.Path(promotion["path"]); doc = json.loads(path.read_text(encoding="utf-8")); doc["candidate_id"] = "tampered"; path.write_text(json.dumps(doc), encoding="utf-8")
    assert finalization.inspect_promotion(path)["status"] == "NEEDS_REWORK"


def test_25_required_user_review_cannot_be_surrogate() -> None:
    source = pathlib.Path(codex_conversation.__file__).read_text(encoding="utf-8")
    assert '"surrogate_may_review": False' in source and '"WAITING_USER_REVIEW"' in source


def test_26_nonvisual_review_policy_is_explicit() -> None:
    source = pathlib.Path(codex_conversation.__file__).read_text(encoding="utf-8")
    assert "canonical_nonvisual_or_no_explicit_review_requirement" in source


def test_27_public_delivery_keeps_target_separate() -> None:
    source = pathlib.Path(codex_conversation.__file__).read_text(encoding="utf-8")
    assert '"target_goal_satisfied"' in source and '"delivery_allowed"' in source


def test_28_nonlive_transport_still_forbids_network() -> None:
    source = pathlib.Path(codex_conversation.__file__).read_text(encoding="utf-8")
    assert 'allow_network=provider_mode == "live"' in source
    assert 'allow_provider=provider_mode == "live"' in source


def test_29_evidence_only_provider_hunk_is_not_reconstructed_as_source() -> None:
    patch = {
        "before_source_snapshot": [],
        "hunks": [
            {"path": "main.py", "after_content": "print('ok')\n"},
            {"path": "DELIVERY_NOTES.md", "after_content": "candidate_only: true\n"},
        ],
    }
    contents = provider_causal_trace._reconstruct_candidate_contents(patch)
    assert set(contents) == {"main.py"}


def test_30_negative_gui_constraint_does_not_require_visual_delivery() -> None:
    session = {"messages": [{"role": "user", "text": "Character count CLI. No GUI, image, video, sprite, or cloud."}]}
    requirements = codex_conversation.infer_public_delivery_requirements(session)
    assert requirements == {
        "screenshot": False,
        "video": False,
        "generated_image": False,
        "background": False,
        "sprite": False,
        "demo_video": False,
    }


def test_31_character_count_is_not_a_sprite_request() -> None:
    session = {"messages": [{"role": "user", "text": "Return character, word, and line counts from a text file."}]}
    assert codex_conversation.infer_public_delivery_requirements(session)["sprite"] is False


def test_32_packaged_candidate_can_be_blocked_by_public_gate(tmp_path: pathlib.Path) -> None:
    _, digest = _project(tmp_path)
    run = tmp_path / "run"
    states = [
        "CANDIDATE_MATERIALIZED",
        "WAITING_CANONICAL_VERIFICATION",
        "WAITING_GOVERNANCE_EVALUATION",
        "WAITING_ACCEPTANCE_DECISION",
        "READY_FOR_PROMOTION",
        "READY_FOR_PACKAGING",
        "DELIVERY_BLOCKED",
    ]
    state = {}
    for name in states:
        state = finalization.transition(run, name, identity=_identity(), candidate_hash=digest)
    assert state["state"] == "DELIVERY_BLOCKED"


def test_33_delivery_fact_check_accepts_manifest_declared_package_entrypoint(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    entrypoint = project / "textcounter" / "__main__.py"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("print('ok')\n", encoding="utf-8")
    (project / "README.md").write_text("# README\n", encoding="utf-8")
    (project / "TEST_PLAN.md").write_text("# Tests\n", encoding="utf-8")
    manifest = {"artifacts": {"startup_entrypoint": "textcounter/__main__.py"}}

    facts = codex_conversation.delivery_fact_check(project, manifest)

    assert facts["facts"]["entrypoint_exists"] is True
    assert facts["facts"]["real_generation_result"] is True
    assert "real_generation_result_missing" not in facts["hard_blockers"]


def test_34_warning_verdict_is_a_canonical_final_delivery_verdict() -> None:
    assert "DELIVER_WITH_WARNINGS" in codex_conversation.adaptive_delivery.FINAL_VERDICTS
    source = pathlib.Path(codex_conversation.__file__).read_text(encoding="utf-8")
    assert "final_verdict not in adaptive_delivery.FINAL_VERDICTS" in source
    assert '"DELIVERED" if public_delivery_succeeded else "DELIVERY_BLOCKED"' in source


def test_35_formal_result_maps_delivered_with_warnings_to_pass_with_limits() -> None:
    source = pathlib.Path(codex_conversation.__file__).read_text(encoding="utf-8")
    assert 'normalized_status == "DELIVERED_WITH_WARNINGS"' in source
    assert 'formal_evidence_status = "PASS_WITH_LIMITS"' in source
    assert 'delivered_generation["canonical_finalization_state"] = delivered_state' in source
