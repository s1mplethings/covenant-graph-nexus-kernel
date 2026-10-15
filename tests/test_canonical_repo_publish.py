from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import canonical_repo_publish as gate


def git(root: pathlib.Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def init_repo(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "CGKN Test")
    git(root, "remote", "add", "origin", str(remote))
    (root / ".gitignore").write_text(".cgkn/\n__pycache__/\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(root, "add", "--", ".gitignore", "scripts/example.py")
    git(root, "commit", "-m", "chore: initialize fixture")
    git(root, "push", "-u", "origin", "main")
    return root, remote


@pytest.mark.parametrize(
    ("path", "classification", "action"),
    [
        ("mystery.bin", "UNKNOWN", "BLOCK"),
        ("artifacts/run.json", "RUNTIME", "EXCLUDE"),
        ("generated/app.py", "GENERATED", "EXCLUDE"),
        ("credentials.json", "SECRET", "BLOCK"),
        ("tests/test_app.py", "TEST", "COMMIT"),
        ("benchmarks/project_generation_v1/cases.json", "TEST", "COMMIT"),
        ("examples/mvp-runtime/hello-pipeline/tree.json", "TEST", "COMMIT"),
        ("config/provider_profiles/project-generation-external-api.json", "CONTRACT", "COMMIT"),
        ("src/app.py", "SOURCE", "COMMIT"),
        (".github/workflows/ci.yml", "SOURCE", "COMMIT"),
        (".gitignore", "CURRENT_DOC", "COMMIT"),
        ("legacy/pre_mvp_reset/README.md", "SOURCE", "COMMIT"),
        (".cgnk/governance/governance.lock.json", "CURRENT_GOVERNANCE", "COMMIT"),
    ],
)
def test_file_policy(path: str, classification: str, action: str) -> None:
    found, _ = gate.classify_path(path)
    assert found == classification
    if found in gate.COMMIT_CLASSES:
        assert action == "COMMIT"
    elif found in gate.EXCLUDE_CLASSES:
        assert action == "EXCLUDE"
    else:
        assert action == "BLOCK"


def test_force_push_options_are_always_blocked() -> None:
    for option in ("-f", "--force", "--force-with-lease"):
        with pytest.raises(gate.PublishBlocked, match="BLOCKED_FORCE_PUSH"):
            gate.reject_force_options([option])


def test_consumer_migrations_require_explicit_review() -> None:
    assert gate.classify_path("drizzle/0017_feature.sql")[0] == "MIGRATION"


def test_environment_key_reference_is_not_secret_content(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "src" / "provider.ts"
    path.parent.mkdir()
    path.write_text("const request = { apiKey: env.QWEN_API_KEY };\n", encoding="utf-8")
    assert gate.classify_path("src/provider.ts", tmp_path)[0] == "SOURCE"


def test_literal_key_remains_secret_content(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "src" / "provider.ts"
    path.parent.mkdir()
    literal = "const request = { apiKey: '" + "sk-super-secret-value-123456" + "' };\n"
    path.write_text(literal, encoding="utf-8")
    assert gate.classify_path("src/provider.ts", tmp_path)[0] == "SECRET"


def test_staged_path_validation_counts_rename_as_delete_plus_add(tmp_path: pathlib.Path) -> None:
    root, _ = init_repo(tmp_path)
    old_path = root / "scripts" / "example.py"
    new_path = root / "scripts" / "renamed.py"
    old_path.rename(new_path)
    git(root, "add", "--", "scripts/example.py", "scripts/renamed.py")
    tree = gate.validate_staged_set(root, ["scripts/example.py", "scripts/renamed.py"])
    assert tree


def test_test_receipt_decodes_utf8_output_independent_of_windows_locale(tmp_path: pathlib.Path) -> None:
    root, _ = init_repo(tmp_path)
    (root / "scripts" / "example.py").write_text("VALUE = 2\n", encoding="utf-8")
    manifest = gate.build_change_manifest(root)
    receipt_path = root / ".cgkn" / "publish" / "test_receipt.json"
    receipt = gate.run_tests_and_write_receipt(
        root,
        manifest,
        ['python -c "import sys; sys.stdout.buffer.write(\'通过\'.encode(\'utf-8\'))"'],
        receipt_path,
    )
    assert receipt["scoped_verdict"] == "PASS"
    assert "通过" in receipt["tests"][0]["stdout_tail"]


def test_target_branch_requires_local_baseline_match(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = init_repo(tmp_path)
    git(root, "switch", "--detach")
    (root / "scripts" / "example.py").write_text("VALUE = 2\n", encoding="utf-8")
    manifest = gate.build_change_manifest(root)
    identity = gate._read_source_identity(root)
    receipt = {"scoped_verdict":"PASS","source_identity_hash":identity["source_identity_hash"],"changed_paths":manifest["commit_files"],"tests":[{"status":"PASS"}]}
    receipt["test_receipt_hash"] = gate.canonical_hash(receipt, ("test_receipt_hash", "created_at"))
    receipt_path = root / ".cgkn" / "publish" / "test_receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(gate, "run_version_gate", lambda _root, _command=None: {"status":"PASS"})
    result = gate.publish(root, message="fix: publish detached consumer", test_receipt_path=receipt_path, target_branch="main")
    assert result["push_verified"] is True


def test_publish_can_create_a_new_remote_branch_from_bound_baseline(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, remote = init_repo(tmp_path)
    git(root, "switch", "-c", "feature")
    (root / "scripts" / "example.py").write_text("VALUE = 2\n", encoding="utf-8")
    manifest = gate.build_change_manifest(root)
    receipt = {"scoped_verdict": "PASS", "source_identity_hash": manifest["source_identity_hash"], "changed_paths": manifest["commit_files"], "tests": [{"status": "PASS"}]}
    receipt["test_receipt_hash"] = gate.canonical_hash(receipt, ("test_receipt_hash", "created_at"))
    receipt_path = root / ".cgkn" / "publish" / "test_receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(gate, "run_version_gate", lambda _root, _command=None: {"status": "PASS"})
    result = gate.publish(root, message="feat: publish new branch", test_receipt_path=receipt_path, target_branch="feature")
    assert result["push_verified"] is True
    assert result["remote_before_sha"] == ""
    assert git(root, "rev-parse", "HEAD") == subprocess.run(["git", "--git-dir", str(remote), "rev-parse", "refs/heads/feature"], text=True, capture_output=True, check=True).stdout.strip()


def test_resume_pushes_only_verified_commit_after_post_commit_interruption(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = init_repo(tmp_path)
    (root / "scripts" / "example.py").write_text("VALUE = 2\n", encoding="utf-8")
    manifest = gate.build_change_manifest(root)
    receipt = {
        "scoped_verdict": "PASS",
        "source_identity_hash": manifest["source_identity_hash"],
        "changed_paths": manifest["commit_files"],
        "tests": [{"status": "PASS"}],
    }
    receipt["test_receipt_hash"] = gate.canonical_hash(receipt, ("test_receipt_hash", "created_at"))
    runtime = root / ".cgkn" / "publish"
    runtime.mkdir(parents=True)
    manifest_path = runtime / "change_manifest.json"
    receipt_path = runtime / "test_receipt.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    git(root, "add", "--", *manifest["commit_files"])
    git(root, "commit", "-m", "fix: verified interrupted commit")
    monkeypatch.setattr(gate, "run_version_gate", lambda _root, _command=None: {"status": "PASS"})
    result = gate.resume_publish(
        root,
        target_branch="main",
        test_receipt_path=receipt_path,
        manifest_path=manifest_path,
    )
    assert result["push_verified"] is True
    assert result["resumed_after_verified_commit"] is True


def test_git_failure_is_blocked_not_clean(tmp_path: pathlib.Path) -> None:
    def broken(_root: pathlib.Path, _args: list[str]) -> dict:
        return {"ok": False, "returncode": 128, "stderr": "boom"}

    with pytest.raises(gate.PublishBlocked, match="BLOCKED_GIT_STATE"):
        gate.repository_state(tmp_path, broken)


def test_staging_set_mismatch_is_blocked(tmp_path: pathlib.Path) -> None:
    def runner(_root: pathlib.Path, args: list[str]) -> dict:
        stdout = "wrong.py\n" if args[:3] == ["diff", "--cached", "--name-only"] else "tree\n"
        return {"ok": True, "returncode": 0, "stdout": stdout, "stderr": ""}

    with pytest.raises(gate.PublishBlocked, match="STAGING_SET_MISMATCH"):
        gate.validate_staged_set(tmp_path, ["right.py"], runner)


def test_stale_or_partial_test_receipt_is_blocked(tmp_path: pathlib.Path) -> None:
    root, _ = init_repo(tmp_path)
    (root / "scripts" / "example.py").write_text("VALUE = 2\n", encoding="utf-8")
    manifest = gate.build_change_manifest(root)
    receipt = {"scoped_verdict": "PASS", "source_identity_hash": "stale", "changed_paths": manifest["commit_files"]}
    with pytest.raises(gate.PublishBlocked, match="TEST_EVIDENCE_STALE"):
        gate.verify_test_binding(root, manifest, receipt)


def test_preexisting_staged_change_is_blocked(tmp_path: pathlib.Path) -> None:
    root, _ = init_repo(tmp_path)
    (root / "scripts" / "example.py").write_text("VALUE = 2\n", encoding="utf-8")
    git(root, "add", "--", "scripts/example.py")
    with pytest.raises(gate.PublishBlocked, match="BLOCKED_PREEXISTING_STAGED_CHANGES"):
        gate.publish(root, message="fix: reject staged state", test_receipt_path=root / "missing.json")


def test_version_gate_failure_is_classified(tmp_path: pathlib.Path) -> None:
    root, _ = init_repo(tmp_path)
    with pytest.raises(gate.PublishBlocked, match="VERSION_GATE_FAILED"):
        gate.run_version_gate(root)


def test_explicit_consumer_version_gate_runs_through_command_shell(tmp_path: pathlib.Path) -> None:
    root, _ = init_repo(tmp_path)
    command = f'"{sys.executable}" -c "print(\'consumer gate pass\')"'
    assert gate.run_version_gate(root, command)["status"] == "PASS"


def test_remote_sha_mismatch_blocks_false_success(tmp_path: pathlib.Path) -> None:
    calls = 0
    def runner(_root: pathlib.Path, args: list[str]) -> dict:
        nonlocal calls
        calls += 1
        return {"ok": True, "returncode": 0, "stdout": "different\n" if args[0] == "rev-parse" else "", "stderr": ""}

    with pytest.raises(gate.PublishBlocked, match="PUSH_UNVERIFIED"):
        gate.verify_remote_sha(tmp_path, "main", "expected", runner)
    assert calls == 2


def test_happy_path_commits_pushes_and_verifies_remote(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, remote = init_repo(tmp_path)
    (root / "scripts" / "example.py").write_text("VALUE = 2\n", encoding="utf-8")
    manifest = gate.build_change_manifest(root)
    identity = gate._read_source_identity(root)
    receipt = {
        "kind": "CGKNTestReceipt", "scoped_verdict": "PASS",
        "source_identity_hash": identity["source_identity_hash"],
        "changed_paths": manifest["commit_files"], "tests": [{"status": "PASS"}],
    }
    receipt["test_receipt_hash"] = gate.canonical_hash(receipt, ("test_receipt_hash", "created_at"))
    receipt_path = root / ".cgkn" / "publish" / "test_receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(gate, "run_version_gate", lambda _root: {"status": "PASS"})

    result = gate.publish(root, message="fix: verify canonical publish", test_receipt_path=receipt_path)

    assert result["push_verified"] is True
    assert git(root, "status", "--porcelain") == ""
    assert git(root, "rev-parse", "HEAD") == subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"], text=True, capture_output=True, check=True
    ).stdout.strip()


def test_post_commit_command_dirtying_tree_blocks_push(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = init_repo(tmp_path)
    (root / "scripts" / "example.py").write_text("VALUE = 2\n", encoding="utf-8")
    manifest = gate.build_change_manifest(root)
    identity = gate._read_source_identity(root)
    receipt = {
        "scoped_verdict": "PASS", "source_identity_hash": identity["source_identity_hash"],
        "changed_paths": manifest["commit_files"], "tests": [{"status": "PASS"}],
    }
    receipt["test_receipt_hash"] = gate.canonical_hash(receipt, ("test_receipt_hash", "created_at"))
    receipt_path = root / ".cgkn" / "publish" / "test_receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(gate, "run_version_gate", lambda _root: {"status": "PASS"})
    command = f'{sys.executable} -c "from pathlib import Path; Path(\'unexpected.txt\').write_text(\'dirty\')"'

    with pytest.raises(gate.PublishBlocked, match="POST_COMMIT_DIRTY"):
        gate.publish(root, message="fix: detect post check mutation", test_receipt_path=receipt_path, post_commit_commands=[command])
    assert git(root, "rev-parse", "origin/main") != git(root, "rev-parse", "HEAD")


def test_remote_race_is_detected_before_push(tmp_path: pathlib.Path) -> None:
    calls: list[list[str]] = []
    def runner(_root: pathlib.Path, args: list[str]) -> dict:
        calls.append(args)
        if args[:2] == ["rev-parse", "origin/main"]:
            return {"ok": True, "stdout": "new-remote\n", "stderr": "", "returncode": 0}
        return {"ok": True, "stdout": "", "stderr": "", "returncode": 0}

    with pytest.raises(gate.PublishBlocked, match="REMOTE_HEAD_CHANGED"):
        gate.verify_remote_baseline(tmp_path, "main", "old-remote", runner)
    assert not any(call and call[0] == "push" for call in calls)


def test_transient_push_retry_rechecks_remote_without_force(tmp_path: pathlib.Path) -> None:
    calls: list[list[str]] = []
    push_count = 0
    def runner(_root: pathlib.Path, args: list[str]) -> dict:
        nonlocal push_count
        calls.append(list(args))
        if args[0] == "push":
            push_count += 1
            if push_count == 1:
                return {"ok": False, "stdout": "", "stderr": "SSL_ERROR_SYSCALL", "returncode": 128}
        stdout = "baseline\n" if args[:2] == ["rev-parse", "origin/main"] else ""
        return {"ok": True, "stdout": stdout, "stderr": "", "returncode": 0}

    gate.normal_push_with_retry(tmp_path, "main", "baseline", ["push", "origin", "main"], runner)
    assert push_count == 2
    assert sum(call[0] == "fetch" for call in calls) == 2
    assert all(not gate.FORBIDDEN_FORCE_OPTIONS.intersection(call) for call in calls)


def test_generated_project_uses_same_lightweight_file_policy() -> None:
    assert gate.classify_path("src/widget.py")[0] == "SOURCE"
    assert gate.classify_path("tests/test_widget.py")[0] == "TEST"
    assert gate.classify_path("dist/widget.zip")[0] == "GENERATED"


def test_fast_ci_workflow_is_bounded_and_provider_free() -> None:
    workflow = (ROOT / ".github" / "workflows" / "repository-fast-ci.yml").read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "timeout-minutes: 12" in workflow
    assert "product_direction_gate.py" in workflow
    assert "test_kernel_contract.py" in workflow
    assert "provider" not in workflow.lower()


def test_source_has_no_implicit_or_force_staging() -> None:
    source = (ROOT / "scripts" / "canonical_repo_publish.py").read_text(encoding="utf-8")
    assert '"add", "."' not in source
    assert '"add", "-A"' not in source
    assert '"push", "--force"' not in source
