from __future__ import annotations

import json
import pathlib
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for value in (ROOT, SCRIPTS):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

import cgkn_runtime_supervisor as runtime
import cgkn_supervision_protocol as protocol
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
    result, route, _ = _run(
        _draft(
            "repair_kernel",
            "kernel",
            evidence_ref="validator-stale-identity.json",
            targets=["scripts/canonical_evidence_hash.py", "tests/test_false_pass_auditor.py"],
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
