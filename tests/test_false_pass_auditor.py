from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for value in (ROOT, SCRIPTS):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

import cgkn_runtime_supervisor as runtime
import cgkn_supervision_protocol as protocol
import codex_conversation as production_bridge
import governed_kernel_repair


_TEMP_OWNERS: list[tempfile.TemporaryDirectory] = []


class InjectedAuditor:
    def __init__(self, draft: dict):
        self.draft = draft
        self.calls = 0

    def run(self, checkpoint: dict, thread_id: str = "") -> dict:
        self.calls += 1
        return protocol.build_result(checkpoint, thread_id or "false-pass-thread", self.draft)


def _draft(action: str, scope: str, *, evidence_ref: str = "fault.json", targets: list[str] | None = None) -> dict:
    return {
        "action": action,
        "scope": scope,
        "summary": f"Injected audit result: {action}",
        "diagnosis": [f"Concrete contradiction found in {evidence_ref}"],
        "evidence_refs": [] if action == "resume" else [
            {"role": "fault_injection", "ref": evidence_ref, "sha256": "a" * 64, "claim": "positive claim is contradicted"}
        ],
        "guidance": [],
        "repair_targets": list(targets or []),
        "acceptance_checks": ["Rerun the exact checkpoint."],
        "known_limits": [],
    }


def _run(draft: dict, checkpoint_type: str = "integration_complete") -> tuple[dict, dict, pathlib.Path]:
    temporary = tempfile.TemporaryDirectory()
    _TEMP_OWNERS.append(temporary)
    state_dir = pathlib.Path(temporary.name)
    checkpoint = protocol.emit_checkpoint(
        state_dir,
        checkpoint_type,
        repository_root=ROOT,
        reason="CGKN proposes a positive transition",
        requested_action="resume",
        context_refs=[{"role": "fault", "ref": "fault.json", "sha256": "a" * 64}],
    )
    adapter = InjectedAuditor(draft)
    host = runtime.SupervisorHost(ROOT, state_dir, adapter)
    result = host.process_next()
    assert result is not None
    route = (state_dir / "routes" / f"{checkpoint['checkpoint_id']}.json").read_text(encoding="utf-8")
    return result, json.loads(route), state_dir


def test_case_a_requirement_coverage_false_pass_routes_provider_planner_repair() -> None:
    result, route, _ = _run(
        _draft("rework_project", "requirements", evidence_ref="plan-without-export.json", targets=["planner.export"])
    )
    assert result["action"] == "rework_project"
    assert route["route_type"] == "provider_repair_required"
    assert route["provider_authoring_required"] is True


def test_case_b_semantic_integration_false_pass_repairs_only_integration() -> None:
    result, route, _ = _run(
        _draft("rework_project", "integration", evidence_ref="GET-scenes-vs-scene.json", targets=["integration.api_contract"])
    )
    assert result["scope"] == "integration"
    assert route["repair_targets"] == ["integration.api_contract"]


def test_case_c_stale_visual_evidence_rechecks_without_provider() -> None:
    result, route, _ = _run(
        _draft("recheck_evidence", "identity", evidence_ref="visual-AAA-candidate-BBB.json"),
        checkpoint_type="pre_public_delivery",
    )
    assert result["action"] == "recheck_evidence"
    assert route["route_type"] == "canonical_verification_rerun_required"
    assert route["provider_authoring_forbidden"] is True


def test_case_d_actual_kernel_bug_enters_governed_repair() -> None:
    result, route, state_dir = _run(
        _draft(
            "repair_kernel",
            "kernel",
            evidence_ref="validator-stale-identity.json",
            targets=["scripts/validator.py", "tests/test_validator.py"],
        ),
        checkpoint_type="pre_public_delivery",
    )
    checkpoint = {"checkpoint_id": result["checkpoint_id"], "checkpoint_sha256": result["checkpoint_sha256"]}
    request = governed_kernel_repair.build_repair_request(
        result,
        checkpoint,
        reproduction_checks=["python -m pytest tests/test_false_pass_auditor.py -q"],
    )
    assert route["route_type"] == "governed_kernel_repair_required"
    assert request["workflow"][0] == "reproduce_false_pass"
    assert all(not target.startswith("generated/") for target in request["repair_targets"])

    with tempfile.TemporaryDirectory() as raw_repository:
        repository = pathlib.Path(raw_repository)
        (repository / "scripts").mkdir()
        (repository / "tests").mkdir()
        (repository / "scripts" / "validator.py").write_text("ACCEPTS_STALE = True\n", encoding="utf-8")
        (repository / "tests" / "test_validator.py").write_text("def test_stale(): pass\n", encoding="utf-8")

        def fake_codex(argv, **kwargs):
            isolated = pathlib.Path(argv[argv.index("--cd") + 1])
            (isolated / "scripts" / "validator.py").write_text("ACCEPTS_STALE = False\n", encoding="utf-8")
            (isolated / "tests" / "test_validator.py").write_text("def test_stale(): assert True\n", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, stdout="fixed", stderr="")

        def fake_test(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout="1 passed", stderr="")

        repair_receipt = governed_kernel_repair.execute_repair(
            request,
            repository,
            runner=fake_codex,
            test_runner=fake_test,
            metrics_state_dir=state_dir,
        )
        assert repair_receipt["status"] == "PASS"
        assert repair_receipt["original_checkpoint_must_be_reemitted"] is True

    protocol.emit_checkpoint(
        state_dir,
        "pre_public_delivery",
        repository_root=ROOT,
        reason="original checkpoint re-emitted after governed kernel repair",
        requested_action="resume",
        context_refs=[{"role": "regression", "ref": "test_validator.py", "sha256": "c" * 64}],
    )
    resume_adapter = InjectedAuditor(_draft("resume", "none"))
    resumed = runtime.SupervisorHost(ROOT, state_dir, resume_adapter).process_next()
    assert resumed is not None and resumed["action"] == "resume"
    metrics = json.loads((state_dir / "supervision_metrics.json").read_text(encoding="utf-8"))
    assert metrics["codex_supervisor_invocation_count"] == 2
    assert metrics["codex_kernel_repair_invocation_count"] == 1


def test_case_e_clean_positive_transition_resumes() -> None:
    result, route, _ = _run(_draft("resume", "none"), checkpoint_type="pre_public_delivery")
    assert result["action"] == "resume"
    assert route["route_type"] == "continue_current_stage"


def test_ordinary_provider_failure_bypasses_codex_invocation() -> None:
    temporary = tempfile.TemporaryDirectory()
    _TEMP_OWNERS.append(temporary)
    state_dir = pathlib.Path(temporary.name)
    checkpoint = protocol.emit_checkpoint(
        state_dir,
        "provider_failure",
        repository_root=ROOT,
        reason="ordinary leaf failed",
        requested_action="resume",
    )
    adapter = InjectedAuditor(_draft("halt", "safety", evidence_ref="should-not-run.json"))
    host = runtime.SupervisorHost(ROOT, state_dir, adapter)
    result = host.process_next()
    assert adapter.calls == 0
    assert result is not None and result["action"] == "resume"
    metrics_path = state_dir / "supervision_metrics.json"
    assert not metrics_path.exists()
    route_path = state_dir / "routes" / f"{checkpoint['checkpoint_id']}.json"
    assert route_path.is_file()


def test_clean_happy_path_uses_exactly_two_sparse_audits() -> None:
    temporary = tempfile.TemporaryDirectory()
    _TEMP_OWNERS.append(temporary)
    state_dir = pathlib.Path(temporary.name)
    for checkpoint_type in ("integration_complete", "pre_public_delivery"):
        protocol.emit_checkpoint(
            state_dir,
            checkpoint_type,
            repository_root=ROOT,
            reason="positive transition proposed",
            requested_action="resume",
            context_refs=[{"role": "evidence", "ref": f"{checkpoint_type}.json", "sha256": "b" * 64}],
        )
    adapter = InjectedAuditor(_draft("resume", "none"))
    host = runtime.SupervisorHost(ROOT, state_dir, adapter)

    first = host.process_next()
    second = host.process_next()

    assert first is not None and first["action"] == "resume"
    assert second is not None and second["action"] == "resume"
    assert adapter.calls == 2
    metrics = json.loads((state_dir / "supervision_metrics.json").read_text(encoding="utf-8"))
    assert metrics["codex_supervisor_invocation_count"] == 2
    assert metrics["codex_kernel_repair_invocation_count"] == 0


def _emit_result(
    state_dir: pathlib.Path,
    draft: dict,
    *,
    checkpoint_type: str = "integration_complete",
) -> tuple[dict, InjectedAuditor]:
    protocol.emit_checkpoint(
        state_dir,
        checkpoint_type,
        repository_root=ROOT,
        reason="production recovery checkpoint",
        requested_action="resume",
        context_refs=[{"role": "evidence", "ref": "evidence.json", "sha256": "d" * 64}],
    )
    adapter = InjectedAuditor(draft)
    result = runtime.SupervisorHost(ROOT, state_dir, adapter).process_next()
    assert result is not None
    return result, adapter


def test_production_recovery_a_provider_repair_reaudits_and_resumes(monkeypatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(production_bridge, "RUNTIME_SUPERVISOR_DIR", str(tmp_path))
    initial, first = _emit_result(
        tmp_path,
        _draft("rework_project", "integration", targets=["integration.api_contract"]),
    )
    provider_calls: list[str] = []
    auditors = [first]

    def repair(audit: dict, route: dict) -> dict:
        provider_calls.extend(route["repair_targets"])
        return {"status": "provider_repair_validated"}

    def reaudit() -> dict:
        result, adapter = _emit_result(tmp_path, _draft("resume", "none"))
        auditors.append(adapter)
        return result

    outcome = production_bridge.run_supervision_recovery_cycle(
        initial,
        reaudit=reaudit,
        handlers={"rework_project": repair},
    )
    assert outcome["outcome"] == "resumed"
    assert provider_calls == ["integration.api_contract"]
    assert outcome["audit_count"] == 2
    assert sum(item.calls for item in auditors) == 2
    assert not (tmp_path / "routes" / "pending_provider_repair.json").exists()


def test_production_recovery_b_stale_evidence_reruns_verifier_without_provider(monkeypatch, tmp_path: pathlib.Path) -> None:
    state_dir = tmp_path / "state"
    project_dir = tmp_path / "project"
    run_dir = tmp_path / "run"
    project_dir.mkdir()
    stale_evidence = run_dir / "provider_validation_receipt.json"
    stale_evidence.parent.mkdir()
    stale_evidence.write_text('{"status":"stale"}\n', encoding="utf-8")
    monkeypatch.setattr(production_bridge, "RUNTIME_SUPERVISOR_DIR", str(state_dir))
    initial, first = _emit_result(
        state_dir,
        _draft("recheck_evidence", "identity", evidence_ref=str(stale_evidence)),
        checkpoint_type="pre_public_delivery",
    )
    verifier_calls = 0
    provider_calls = 0
    auditors = [first]

    def verify(audit: dict, route: dict) -> dict:
        nonlocal verifier_calls
        verifier_calls += 1
        invalidation = production_bridge.invalidate_supervision_evidence(
            audit,
            route,
            project_dir=project_dir,
            production_run_dir=run_dir,
        )
        return {
            **invalidation,
            "status": "canonical_verifier_rerun",
            "provider_invocation_count": 0,
        }

    def reaudit() -> dict:
        result, adapter = _emit_result(
            state_dir, _draft("resume", "none"), checkpoint_type="pre_public_delivery"
        )
        auditors.append(adapter)
        return result

    outcome = production_bridge.run_supervision_recovery_cycle(
        initial,
        reaudit=reaudit,
        handlers={"recheck_evidence": verify},
    )
    assert outcome["outcome"] == "resumed"
    assert verifier_calls == 1
    assert provider_calls == 0
    assert not stale_evidence.exists()
    assert sum(item.calls for item in auditors) == 2
    assert not (state_dir / "routes" / "pending_evidence_recheck.json").exists()


def test_production_recovery_c_governed_kernel_repair_reaudits_and_resumes(monkeypatch, tmp_path: pathlib.Path) -> None:
    state_dir = tmp_path / "state"
    repository = tmp_path / "repository"
    (repository / "scripts").mkdir(parents=True)
    (repository / "tests").mkdir()
    (repository / "scripts" / "validator.py").write_text("ACCEPTS_STALE = True\n", encoding="utf-8")
    (repository / "tests" / "test_validator.py").write_text("def test_stale(): pass\n", encoding="utf-8")
    monkeypatch.setattr(production_bridge, "RUNTIME_SUPERVISOR_DIR", str(state_dir))
    initial, first = _emit_result(
        state_dir,
        _draft(
            "repair_kernel",
            "kernel",
            targets=["scripts/validator.py", "tests/test_validator.py"],
        ),
        checkpoint_type="pre_public_delivery",
    )
    real_execute = governed_kernel_repair.execute_repair
    repair_calls = 0

    def fake_codex(argv, **kwargs):
        isolated = pathlib.Path(argv[argv.index("--cd") + 1])
        (isolated / "scripts" / "validator.py").write_text("ACCEPTS_STALE = False\n", encoding="utf-8")
        (isolated / "tests" / "test_validator.py").write_text("def test_stale(): assert True\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="fixed", stderr="")

    def fake_test(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="1 passed", stderr="")

    def execute_through_real_governance(request, _root, **kwargs):
        nonlocal repair_calls
        repair_calls += 1
        return real_execute(
            request,
            repository,
            runner=fake_codex,
            test_runner=fake_test,
            metrics_state_dir=kwargs.get("metrics_state_dir"),
        )

    monkeypatch.setattr(governed_kernel_repair, "execute_repair", execute_through_real_governance)
    auditors = [first]

    def reaudit() -> dict:
        result, adapter = _emit_result(
            state_dir, _draft("resume", "none"), checkpoint_type="pre_public_delivery"
        )
        auditors.append(adapter)
        return result

    outcome = production_bridge.run_supervision_recovery_cycle(
        initial,
        reaudit=reaudit,
        handlers={"repair_kernel": production_bridge.execute_governed_supervision_repair},
    )
    assert outcome["outcome"] == "resumed"
    assert repair_calls == 1
    assert sum(item.calls for item in auditors) == 2
    metrics = json.loads((state_dir / "supervision_metrics.json").read_text(encoding="utf-8"))
    assert metrics["codex_supervisor_invocation_count"] == 2
    assert metrics["codex_kernel_repair_invocation_count"] == 1


def test_production_recovery_d_two_refusals_stop_at_needs_rework(monkeypatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.setattr(production_bridge, "RUNTIME_SUPERVISOR_DIR", str(tmp_path))
    rejected = _draft("rework_project", "project", targets=["frontend"])
    initial, first = _emit_result(tmp_path, rejected)
    provider_calls = 0
    auditors = [first]

    def repair(_audit: dict, _route: dict) -> dict:
        nonlocal provider_calls
        provider_calls += 1
        return {"status": "provider_repair_validated"}

    def reaudit() -> dict:
        result, adapter = _emit_result(tmp_path, rejected)
        auditors.append(adapter)
        return result

    outcome = production_bridge.run_supervision_recovery_cycle(
        initial,
        reaudit=reaudit,
        handlers={"rework_project": repair},
    )
    assert outcome["outcome"] == "needs_rework"
    assert outcome["evidence_status"] == "NEEDS_REWORK"
    assert outcome["refusal_count"] == production_bridge.MAX_SUPERVISION_REWORK_ROUNDS == 2
    assert provider_calls == 1
    assert sum(item.calls for item in auditors) == 2


def test_production_recovery_e_ordinary_provider_failure_has_zero_codex_calls(tmp_path: pathlib.Path) -> None:
    checkpoint = protocol.emit_checkpoint(
        tmp_path,
        "provider_failure",
        repository_root=ROOT,
        reason="ordinary provider failure",
        requested_action="resume",
    )
    adapter = InjectedAuditor(_draft("halt", "safety"))
    result = runtime.SupervisorHost(ROOT, tmp_path, adapter).process_next()
    assert result is not None and result["action"] == "resume"
    assert adapter.calls == 0
    assert not (tmp_path / "supervision_metrics.json").exists()
    assert (tmp_path / "routes" / f"{checkpoint['checkpoint_id']}.json").is_file()
