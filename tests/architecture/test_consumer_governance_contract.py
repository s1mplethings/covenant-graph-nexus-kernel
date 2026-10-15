"""Bind the canonical governance consumer scenarios to the kernel profile."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import cgkn.governance.consumer as consumer


_SOURCE = Path(__file__).resolve().parents[1] / "test_consumer_governance.py"
_SPEC = importlib.util.spec_from_file_location("cgkn_consumer_governance_scenarios", _SOURCE)
assert _SPEC and _SPEC.loader
_SCENARIOS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCENARIOS)

pytestmark = [pytest.mark.happy_path, pytest.mark.negative, pytest.mark.boundary, pytest.mark.roundtrip, pytest.mark.security, pytest.mark.integration]

for _name in (
    "test_contract_content_is_immutable_at_same_version",
    "test_new_contract_version_is_allowed_when_old_version_remains",
    "test_version_bump_requires_migration_and_weakening_still_needs_review",
    "test_constitutional_removal_needs_user_review",
    "test_path_mapping_and_upward_dependency_propagation",
    "test_unmapped_governed_file_blocks",
    "test_missing_target_and_zero_tests_never_pass",
    "test_unknown_checker_is_not_accepted",
    "test_lock_and_tool_version_mismatch",
    "test_record_requires_clean_tree_and_strict_pass",
    "test_explain_is_read_only",
):
    globals()[_name] = getattr(_SCENARIOS, _name)
    globals()[_name].__module__ = __name__


@pytest.mark.fault_injection
def test_governance_io_and_declaration_failures(tmp_path, monkeypatch) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(consumer.GovernanceError, match="Missing governance file"):
        consumer.read_json(missing)
    missing.write_text("{", encoding="utf-8")
    with pytest.raises(consumer.GovernanceError, match="Invalid JSON"):
        consumer.read_json(missing)

    project = _SCENARIOS.fixture(tmp_path)
    engine = _SCENARIOS.engine(project)
    with pytest.raises(consumer.GovernanceError, match="array"):
        engine._index({}, "capabilities")
    with pytest.raises(consumer.GovernanceError, match="Invalid"):
        engine._index({"capabilities": [{}]}, "capabilities")
    with pytest.raises(consumer.GovernanceError, match="demo@1"):
        engine._index({"capabilities": [{"id": "demo", "version": 1}, {"id": "demo", "version": 1}]}, "capabilities")
    engine.invariants["INV-001@1"].pop("title")
    with pytest.raises(consumer.GovernanceError, match="missing title"):
        engine._validate_declarations()
    engine.invariants["INV-001@1"]["title"] = "Human gate"
    engine.invariants["INV-001@1"]["changePolicy"] = "mutable"
    with pytest.raises(consumer.GovernanceError, match="must require user review"):
        engine._validate_declarations()
    engine.invariants["INV-001@1"]["changePolicy"] = "requires_user_review"
    engine.capabilities["capability.demo.core@1"]["dependsOn"] = ["missing"]
    with pytest.raises(consumer.GovernanceError, match="missing"):
        engine._validate_declarations()

    monkeypatch.setattr(consumer.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="git failed"))
    with pytest.raises(consumer.GovernanceError, match="git failed"):
        consumer.git(project, "status")


@pytest.mark.fault_injection
def test_target_execution_failure_matrix(tmp_path, monkeypatch) -> None:
    project = _SCENARIOS.fixture(tmp_path)
    engine = _SCENARIOS.engine(project)
    assert engine._run_target("missing").code == "TEST_TARGET_MISSING"
    engine.targets["empty"] = {"type": "command", "command": []}
    assert engine._run_target("empty").code == "UNKNOWN_INVARIANT_CHECKER"
    engine.targets["file"] = {"type": "command", "command": ["tool"], "requiredFiles": ["absent"]}
    assert engine._run_target("file").code == "TEST_TARGET_MISSING"

    engine.targets["run"] = {"type": "command", "command": ["tool"], "collectionPattern": "collected"}
    monkeypatch.setattr(consumer.shutil, "which", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(consumer.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("missing tool")))
    assert engine._run_target("run").code == "VERIFICATION_TOOL_MISSING"
    monkeypatch.setattr(consumer.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("tool", 1)))
    assert engine._run_target("run").code == "VERIFICATION_TIMEOUT"
    monkeypatch.setattr(consumer.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="failed"))
    assert engine._run_target("run").code == "VERIFICATION_FAILED"
    monkeypatch.setattr(consumer.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="no tests"))
    assert engine._run_target("run").code == "ZERO_TESTS_COLLECTED"
    monkeypatch.setattr(consumer.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="collected"))
    assert engine._run_target("run").code == "VERIFIED"


@pytest.mark.integration
def test_strict_experiments_record_history_and_cli(tmp_path, monkeypatch, capsys) -> None:
    project = _SCENARIOS.fixture(tmp_path)
    strict = _SCENARIOS.engine(project, strict=True)
    result = strict.verify()
    assert result["status"] in {"PASS", "BLOCK"}
    assert "EXPERIMENTS_VERIFIED" in {item["code"] for item in result["checks"]}

    (project / ".cgnk/governance/history.json").write_text(json.dumps({"commits": ["HEAD"]}), encoding="utf-8")
    _SCENARIOS.run(project, "git", "add", ".cgnk/governance/history.json")
    _SCENARIOS.run(project, "git", "commit", "-m", "add history")
    strict.invariants["INV-001@1"]["effectiveFrom"]["commit"] = "HEAD~1"
    timeline = strict.history()
    assert timeline["status"] == "PASS"
    assert timeline["metrics"]["historicalCommitsChecked"] == 1

    monkeypatch.setattr(strict, "verify", lambda **_kwargs: {"status": "PASS"})
    recorded = strict.record()
    assert recorded["recorded"] is True

    assert consumer.main(["explain", "--project", str(project), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "CGKNConsumerGovernanceResult"
    rendered = consumer.render_human({
        "status": "BLOCK", "changedFiles": ["src/core.py"],
        "affectedCapabilities": ["capability.demo.core"], "affectedInvariants": ["INV-001"],
        "checks": [{"status": "BLOCK", "code": "TEST", "detail": "failed"}], "nextAction": "repair",
    })
    assert "TEST: failed" in rendered and "repair" in rendered


@pytest.mark.negative
def test_history_and_experiment_empty_config_fail_closed(tmp_path) -> None:
    project = _SCENARIOS.fixture(tmp_path)
    engine = _SCENARIOS.engine(project)
    (project / ".cgnk/governance/history.json").write_text('{"commits": []}', encoding="utf-8")
    with pytest.raises(consumer.GovernanceError, match="No historical commits"):
        engine.history()
    (project / ".cgnk/governance/adversarial.json").unlink()
    assert engine._run_experiment_suite("adversarial", expect_block=True).code == "EXPERIMENT_SUITE_MISSING"
    (project / ".cgnk/governance/adversarial.json").write_text('{"cases": []}', encoding="utf-8")
    assert engine._run_experiment_suite("adversarial", expect_block=True).code == "ZERO_EXPERIMENT_CASES"
