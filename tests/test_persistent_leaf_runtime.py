from __future__ import annotations

import base64
import hashlib
import pathlib

import pytest

from scripts.evidence_provenance import EvidenceProvenanceLedger, gate_verified_evidence, sha256_file
from scripts.leaf_collaboration_graph import LeafCollaborationGraph
from scripts.leaf_workspace_manager import LeafWorkspaceManager, summarize_leaf_workspaces, validate_leaf_workspace_layout
from scripts.patch_merge_manager import PatchMergeManager
from scripts.persistent_leaf_runtime import PersistentLeafRuntime
from scripts.product_candidate_manager import ProductCandidateManager, tree_hash
from scripts.test_profile_manager import ProfileLedger, profile_boundary_gate


def _test_artifact(leaf: pathlib.Path, *, command: str = "python -c \"print('ok')\"", status: str = "PASS", exit_code: int = 0, content: str = "ok\n") -> dict:
    artifact = leaf / "test.log"
    artifact.write_text(content, encoding="utf-8")
    return {
        "command": command,
        "status": status,
        "exit_code": exit_code,
        "returncode": exit_code,
        "provenance_status": "observed",
        "artifact_refs": ["test.log"],
        "hashes": {"test.log": hashlib.sha256(artifact.read_bytes()).hexdigest()},
    }


def test_leaf_workspace_isolated_and_has_required_contract_files(tmp_path: pathlib.Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "app.py").write_text("print('base')\n", encoding="utf-8")
    manager = LeafWorkspaceManager(tmp_path / "run", run_id="run_a")

    workspace = manager.create_workspace(
        leaf_id="leaf_a",
        task_id="task_a",
        candidate_dir=candidate,
        task_contract={"allowed_files": ["app.py"]},
        context_packet={"summary": "only relevant context"},
    )

    assert validate_leaf_workspace_layout(workspace["leaf_dir"])["status"] == "PASS"
    with pytest.raises(PermissionError):
        manager.resolve_workspace_path(workspace, "../candidate/app.py")


def test_workspace_identity_counts_only_real_leaf_workspaces(tmp_path: pathlib.Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "app.py").write_text("print('base')\n", encoding="utf-8")
    manager = LeafWorkspaceManager(tmp_path / "run", run_id="run_a")

    workspaces = [
        manager.create_workspace(
            leaf_id=f"leaf_{index}",
            task_id=f"task_{index}",
            candidate_dir=candidate,
            task_contract={"allowed_files": ["app.py"]},
        )
        for index in range(4)
    ]

    summary = summarize_leaf_workspaces(workspaces)

    assert summary["status"] == "PASS"
    assert summary["leaf_workspace_count"] == 4
    assert len(summary["workspace_roots"]) == 4
    assert all(workspace["temp_dir"] in summary["ignored_container_dirs"] for workspace in workspaces)
    assert all(workspace["input_dir"] in summary["ignored_container_dirs"] for workspace in workspaces)


def test_controlled_leaf_connections_enforce_limits_scope_and_cycles(tmp_path: pathlib.Path) -> None:
    graph = LeafCollaborationGraph(tmp_path / "connections.jsonl", run_id="run_a", same_branch_limit=1, cross_branch_limit=1, active_limit=4)
    first = graph.request_connection(
        source_leaf="leaf_a",
        target_leaf="leaf_b",
        source_branch="backend",
        target_branch="backend",
        connection_type="interface_question",
        reason="align function signature",
        requested_information="What is the function signature?",
    )
    assert first["status"] == "approved"
    duplicate = graph.request_connection(
        source_leaf="leaf_a",
        target_leaf="leaf_b",
        source_branch="backend",
        target_branch="backend",
        connection_type="interface_question",
        reason="same question",
        requested_information="What is the function signature?",
    )
    assert duplicate["status"] == "rejected"
    cross = graph.request_connection(
        source_leaf="leaf_a",
        target_leaf="leaf_c",
        source_branch="backend",
        target_branch="frontend",
        connection_type="schema_negotiation",
        reason="public schema",
        requested_information="Which fields are public?",
    )
    assert cross["status"] == "requested"
    msg = graph.append_message(
        connection_id=first["connection_id"],
        sender="leaf_a",
        receiver="leaf_b",
        message_type="status_signal",
        summary="waiting for fixture name",
        token_estimate=20,
    )
    graph.append_message(
        connection_id=first["connection_id"],
        sender="leaf_b",
        receiver="leaf_a",
        message_type="status_signal",
        summary="waiting for schema answer",
        response_to=msg["message_id"],
        token_estimate=20,
    )
    assert graph.detect_circular_waiting()["status"] == "NEEDS_REWORK"
    with pytest.raises(PermissionError):
        graph.append_message(
            connection_id=first["connection_id"],
            sender="leaf_a",
            receiver="leaf_b",
            message_type="implementation_hint",
            summary="Please complete this whole task and approve delivery",
            token_estimate=20,
        )


def test_patch_only_merge_rejects_disallowed_files_and_base_hash_changes(tmp_path: pathlib.Path) -> None:
    candidate = tmp_path / "candidate"
    workspace = tmp_path / "workspace"
    leaf = tmp_path / "leaf"
    candidate.mkdir()
    workspace.mkdir()
    leaf.mkdir()
    (candidate / "app.py").write_text("print('base')\n", encoding="utf-8")
    (workspace / "app.py").write_text("print('changed')\n", encoding="utf-8")
    (workspace / "secret.txt").write_text("bad\n", encoding="utf-8")
    manager = PatchMergeManager(tmp_path / "merge_events.jsonl")

    result = manager.build_leaf_result(
        base_candidate_dir=candidate,
        leaf_workspace_dir=workspace,
        leaf_dir=leaf,
        allowed_files=["app.py"],
        nearest_test_result=_test_artifact(leaf),
    )
    assert result["allowed_files_check"]["status"] == "NEEDS_REWORK"

    (workspace / "secret.txt").unlink()
    result = manager.build_leaf_result(
        base_candidate_dir=candidate,
        leaf_workspace_dir=workspace,
        leaf_dir=leaf,
        allowed_files=["app.py"],
        nearest_test_result=_test_artifact(leaf),
    )
    (candidate / "other.py").write_text("candidate changed\n", encoding="utf-8")
    merge = manager.merge_leaf_result(candidate_dir=candidate, leaf_workspace_dir=workspace, result_manifest=result)
    assert merge["status"] == "NEEDS_REWORK"
    assert merge["reason"] == "base_candidate_hash_changed"
    assert merge["merge_status"] == "REJECTED_STALE_BASE"


def test_merge_rejects_empty_not_evaluated_failed_missing_and_hash_mismatch_tests(tmp_path: pathlib.Path) -> None:
    candidate = tmp_path / "candidate"
    workspace = tmp_path / "workspace"
    leaf = tmp_path / "leaf"
    candidate.mkdir()
    workspace.mkdir()
    leaf.mkdir()
    (candidate / "app.py").write_text("VALUE = 'base'\n", encoding="utf-8")
    (workspace / "app.py").write_text("VALUE = 'leaf'\n", encoding="utf-8")
    manager = PatchMergeManager(tmp_path / "merge_events.jsonl")

    cases = [
        ({"command": "", "status": "PASS", "exit_code": 0}, "REJECTED_NO_TEST"),
        ({"command": "python -c \"print(1)\"", "status": "NOT_EVALUATED", "exit_code": 0}, "REJECTED_TEST_FAILED"),
        (_test_artifact(leaf, status="NEEDS_REWORK", exit_code=1), "REJECTED_TEST_FAILED"),
        ({"command": "python -c \"print(1)\"", "status": "PASS", "exit_code": 0, "provenance_status": "observed", "artifact_refs": ["missing.log"], "hashes": {}}, "REJECTED_EVIDENCE"),
        ({"command": "python -c \"print(1)\"", "status": "PASS", "exit_code": 0, "provenance_status": "observed", "artifact_refs": ["test.log"], "hashes": {"test.log": "bad"}}, "REJECTED_EVIDENCE"),
    ]
    (leaf / "test.log").write_text("ok\n", encoding="utf-8")
    for test_result, expected in cases:
        result = manager.build_leaf_result(
            base_candidate_dir=candidate,
            leaf_workspace_dir=workspace,
            leaf_dir=leaf,
            allowed_files=["app.py"],
            nearest_test_result=test_result,
        )
        merge = manager.merge_leaf_result(candidate_dir=candidate, leaf_workspace_dir=workspace, result_manifest=result)
        assert merge["merge_status"] == expected


def test_merge_rejects_unrelated_nearest_behavior_test(tmp_path: pathlib.Path) -> None:
    candidate = tmp_path / "candidate"
    workspace = tmp_path / "workspace"
    leaf = tmp_path / "leaf"
    candidate.mkdir()
    workspace.mkdir()
    leaf.mkdir()
    (candidate / "app.py").write_text("VALUE = 'base'\n", encoding="utf-8")
    (workspace / "app.py").write_text("VALUE = 'leaf'\n", encoding="utf-8")
    manager = PatchMergeManager(tmp_path / "merge.jsonl")
    result = manager.build_leaf_result(
        base_candidate_dir=candidate,
        leaf_workspace_dir=workspace,
        leaf_dir=leaf,
        allowed_files=["app.py"],
        nearest_test_result=_test_artifact(leaf, command="python -m py_compile README.md"),
    )

    merge = manager.merge_leaf_result(candidate_dir=candidate, leaf_workspace_dir=workspace, result_manifest=result)

    assert merge["merge_status"] == "REJECTED_UNRELATED_TEST"


def test_valid_test_merge_and_integration_failure_rolls_back_candidate(tmp_path: pathlib.Path) -> None:
    candidate = tmp_path / "candidate"
    workspace = tmp_path / "workspace"
    leaf = tmp_path / "leaf"
    candidate.mkdir()
    workspace.mkdir()
    leaf.mkdir()
    (candidate / "app.py").write_text("VALUE = 'base'\n", encoding="utf-8")
    (workspace / "app.py").write_text("VALUE = 'leaf'\n", encoding="utf-8")
    manager = PatchMergeManager(tmp_path / "merge_events.jsonl")
    test_result = _test_artifact(leaf, command="python -c \"from pathlib import Path; assert 'leaf' in Path('app.py').read_text()\"")
    result = manager.build_leaf_result(
        base_candidate_dir=candidate,
        leaf_workspace_dir=workspace,
        leaf_dir=leaf,
        allowed_files=["app.py"],
        nearest_test_result=test_result,
    )

    merge = manager.merge_leaf_result(candidate_dir=candidate, leaf_workspace_dir=workspace, result_manifest=result)
    assert merge["merge_status"] == "MERGED"
    assert "leaf" in (candidate / "app.py").read_text(encoding="utf-8")

    stale_workspace = tmp_path / "workspace2"
    stale_leaf = tmp_path / "leaf2"
    stale_workspace.mkdir()
    stale_leaf.mkdir()
    (stale_workspace / "app.py").write_text("VALUE = 'bad'\n", encoding="utf-8")
    bad_result = manager.build_leaf_result(
        base_candidate_dir=candidate,
        leaf_workspace_dir=stale_workspace,
        leaf_dir=stale_leaf,
        allowed_files=["app.py"],
        nearest_test_result=_test_artifact(stale_leaf, command="python -c \"raise SystemExit(1)\""),
    )
    bad_merge = manager.merge_leaf_result(candidate_dir=candidate, leaf_workspace_dir=stale_workspace, result_manifest=bad_result)
    assert bad_merge["merge_status"] == "REJECTED_TEST_FAILED"
    assert "leaf" in (candidate / "app.py").read_text(encoding="utf-8")


def test_product_candidate_requires_same_candidate_for_formal_stages(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
    manager = ProductCandidateManager(tmp_path / "candidate.json", run_id="run_a")
    candidate = manager.create_candidate(project_dir=project, requirement_version="1")

    events = [
        {"stage": "integration", "candidate_id": candidate["candidate_id"]},
        {"stage": "screenshot", "candidate_id": "old_candidate"},
    ]
    assert manager.validate_stage_candidate(events)["status"] == "NEEDS_REWORK"
    old_hash = candidate["project_tree_hash"]
    (project / "app.py").write_text("print('new')\n", encoding="utf-8")
    invalidated = manager.invalidated_evidence_after_change(
        [{"stage": "screenshot", "candidate_id": candidate["candidate_id"], "project_tree_hash": old_hash}],
        old_hash=old_hash,
        new_hash=tree_hash(project),
    )
    assert invalidated["status"] == "NEEDS_REWORK"


def test_candidate_manifest_updates_patch_ids_and_hash_after_merge(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("VALUE = 'base'\n", encoding="utf-8")
    manager = ProductCandidateManager(tmp_path / "candidate.json", run_id="run_a")
    candidate = manager.create_candidate(project_dir=project, requirement_version="1")
    previous_hash = candidate["project_tree_hash"]
    (project / "app.py").write_text("VALUE = 'merged'\n", encoding="utf-8")

    update = manager.update_after_merge(
        project_dir=project,
        patch_id="patch_a",
        expected_previous_hash=previous_hash,
        task_ledger_offset=10,
        evidence_ledger_offset=20,
        interface_version="2",
    )

    assert update["status"] == "PASS"
    current = manager.current()
    assert current["accepted_patch_ids"] == ["patch_a"]
    assert current["project_tree_hash"] == tree_hash(project)
    assert current["task_ledger_offset"] == 10
    assert current["evidence_ledger_offset"] == 20
    assert current["interface_version"] == "2"

    stale = manager.update_after_merge(
        project_dir=project,
        patch_id="patch_b",
        expected_previous_hash=previous_hash,
        task_ledger_offset=11,
        evidence_ledger_offset=21,
    )
    assert stale["status"] == "NEEDS_REWORK"
    assert "patch_b" not in manager.current()["accepted_patch_ids"]


def test_evidence_provenance_rejects_claimed_and_fake_png(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    fake = root / "fake.png"
    fake.write_bytes(b"\x89PNG\r\n\x1a\nnot a valid png")
    ledger = EvidenceProvenanceLedger(tmp_path / "provenance.jsonl", run_id="run_a", candidate_id="candidate_a", root=root)
    claimed = ledger.append(
        task_id="ui",
        leaf_id="leaf_a",
        source_process_id="runner",
        source_type="runner",
        provenance_status="claimed",
        artifact_refs=["fake.png"],
        result="PASS",
    )
    rejected_claim = ledger.verify_artifact(claimed["evidence_id"], require_png=True)
    assert rejected_claim["provenance_status"] == "rejected"

    observed = ledger.append(
        task_id="ui",
        leaf_id="leaf_a",
        source_process_id="browser_pid",
        source_type="browser",
        provenance_status="observed",
        artifact_refs=["fake.png"],
        hashes={"sha256": sha256_file(fake)},
        result="PASS",
    )
    rejected_png = ledger.verify_artifact(observed["evidence_id"], require_png=True)
    assert rejected_png["data"]["invalid_png"] == ["fake.png"]
    assert gate_verified_evidence(ledger.rows())["status"] == "NEEDS_REWORK"


def test_valid_png_evidence_can_be_verified(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    valid = root / "valid.png"
    valid.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="))
    ledger = EvidenceProvenanceLedger(tmp_path / "provenance.jsonl", run_id="run_a", candidate_id="candidate_a", root=root)
    observed = ledger.append(
        task_id="ui",
        leaf_id="leaf_a",
        source_process_id="browser_pid",
        source_type="browser",
        provenance_status="observed",
        artifact_refs=["valid.png"],
        hashes={"sha256": sha256_file(valid)},
        result="PASS",
    )
    verified = ledger.verify_artifact(observed["evidence_id"], require_png=True)
    assert verified["provenance_status"] == "verified"
    assert gate_verified_evidence(ledger.rows())["status"] == "PASS"


def test_persistent_leaf_runtime_keeps_changes_in_workspace_until_l2_merge(tmp_path: pathlib.Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "app.py").write_text("VALUE = 'base'\n", encoding="utf-8")
    runtime = PersistentLeafRuntime(tmp_path / "run", run_id="run_a")

    def action(workspace: pathlib.Path, context: dict) -> dict:
        (workspace / "app.py").write_text("VALUE = 'leaf'\n", encoding="utf-8")
        assert (candidate / "app.py").read_text(encoding="utf-8") == "VALUE = 'base'\n"
        return {"interface_impact": {"public_api": "unchanged"}}

    result = runtime.run_leaf(
        leaf_id="leaf_a",
        task_id="task_a",
        candidate_dir=candidate,
        task_contract={"goal": "change value"},
        context_packet={},
        allowed_files=["app.py"],
        action=action,
        profile="micro",
        nearest_test_command="python -c \"from pathlib import Path; assert 'leaf' in Path('app.py').read_text()\"",
    )

    assert result["status"] == "PASS"
    assert (candidate / "app.py").read_text(encoding="utf-8") == "VALUE = 'leaf'\n"
    assert pathlib.Path(result["workspace"]["leaf_dir"], "patch.diff").read_text(encoding="utf-8")


def test_profile_boundary_rejects_reused_result_file_and_mixed_candidate(tmp_path: pathlib.Path) -> None:
    result_file = tmp_path / "focused_result.json"
    result_file.write_text('{"ok": true}\n', encoding="utf-8")
    browser_result = tmp_path / "browser_result.json"
    browser_result.write_text('{"ok": true}\n', encoding="utf-8")
    ledger = ProfileLedger(tmp_path / "profiles.jsonl", run_id="run_a", candidate_id="candidate_a", commit_sha="commit_a")
    ledger.append_result(
        profile="focused",
        command="pytest focused",
        result_file=str(result_file),
        status="PASS",
        exit_code=0,
        collected=1,
        passed=1,
        failed=0,
        skipped=0,
    )
    ledger.append_result(
        profile="full_all",
        command="python -m pytest -q",
        result_file=str(result_file),
        status="PASS",
        exit_code=0,
        collected=1,
        passed=1,
        failed=0,
        skipped=0,
    )
    ledger.append_result(
        profile="browser",
        command="playwright",
        result_file=str(browser_result),
        status="PASS",
        exit_code=0,
        candidate_id="old_candidate",
        collected=1,
        passed=1,
        failed=0,
        skipped=0,
    )

    gate = profile_boundary_gate(ledger.rows(), required_profiles=["focused", "full_all", "browser"], candidate_id="candidate_a", run_id="run_a", commit_sha="commit_a")

    assert gate["status"] == "NEEDS_REWORK"
    assert gate["duplicate_result_files"]
    assert gate["duplicate_result_hashes"]
    assert gate["invalid_commands"]
    assert gate["wrong_candidate"]


def test_profile_boundary_rejects_old_run_commit_and_uncategorized_skips(tmp_path: pathlib.Path) -> None:
    result_file = tmp_path / "e2e_result.json"
    result_file.write_text('{"ok": true}\n', encoding="utf-8")
    ledger = ProfileLedger(tmp_path / "profiles.jsonl", run_id="run_old", candidate_id="candidate_a", commit_sha="commit_old")
    ledger.append_result(
        profile="e2e",
        command="python -m pytest -q -m e2e",
        result_file=str(result_file),
        status="PASS",
        exit_code=0,
        collected=343,
        passed=0,
        failed=0,
        skipped=343,
        skip_reasons={"only partially classified": 1},
    )

    gate = profile_boundary_gate(ledger.rows(), required_profiles=["e2e"], candidate_id="candidate_a", run_id="run_current", commit_sha="commit_current")

    assert gate["status"] == "NEEDS_REWORK"
    assert gate["wrong_run"]
    assert gate["wrong_commit"]
    assert gate["uncategorized_skips"]


def test_profile_boundary_accepts_current_repo_default_and_full_all_contracts(tmp_path: pathlib.Path) -> None:
    repo_result = tmp_path / "repo_default_result.json"
    repo_result.write_text('{"ok": true, "profile": "repo_default"}\n', encoding="utf-8")
    full_result = tmp_path / "full_all_result.json"
    full_result.write_text('{"ok": true, "profile": "full_all"}\n', encoding="utf-8")
    ledger = ProfileLedger(tmp_path / "profiles.jsonl", run_id="run_a", candidate_id="candidate_a", commit_sha="commit_a")
    ledger.append_result(
        profile="repo_default",
        command="python -m pytest -q",
        result_file=str(repo_result),
        status="PASS",
        exit_code=0,
        collected=10,
        passed=10,
        failed=0,
        skipped=0,
    )
    ledger.append_result(
        profile="full_all",
        command="python scripts/run_test_profile.py --profile full_all",
        result_file=str(full_result),
        status="PASS",
        exit_code=0,
        collected=12,
        passed=10,
        failed=0,
        skipped=2,
        skip_reasons={"profile-marked unavailable externally": 2},
    )

    gate = profile_boundary_gate(ledger.rows(), required_profiles=["repo_default", "full_all"], candidate_id="candidate_a", run_id="run_a", commit_sha="commit_a")

    assert gate["status"] == "PASS"
