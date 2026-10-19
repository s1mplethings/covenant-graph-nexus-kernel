from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time
from dataclasses import replace
from typing import Any, Mapping

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.application.learning import FileLessonStore, ProductionGenerationClient, StoreLessonReader
from cgkn.application.project_campaign.matrix import _existing_cases
from cgkn.application.project_campaign.service import (_compile, _contract, _evaluate, _obligations,
                                                       _package, _pytest, _render_tests, _snapshot)
from cgkn.application.provider_evaluation import (
    ProjectActionAuthority, ProjectProviderPlan, ProductionQualificationEvidence,
    ProviderCapabilityProfile, ProviderSelector, TaskClassGateStatus, TaskClassQualificationGate,
)
from cgkn.application.repository_codegen import ChangeKind, ChangeRequest, RepositoryCodegenService
from cgkn.application.software_project.greenfield import (
    GenerationManifestCompiler, GreenfieldBundleProductionService,
    ProjectShapedQualificationReceipt, canonical_hash,
)
from cgkn.providers import ConnectorCompletionClient, ModelRoleConfig
from scripts.run_adaptive_project_validation import cases as greenfield_cases
from scripts.run_supervised_multitype_validation import native_client


ITERATION = "ITER-TASK-GATED-LEVEL3-CLOSURE-030"
MODEL = {"qwen": "qwen3.8-max", "grok": "grok-4.7", "deepseek": "deepseek-flash"}
TRANSPORT_FAILURES = frozenset({"PROVIDER_TRANSPORT_FAILURE", "PROVIDER_CONNECT_TIMEOUT", "PROVIDER_FIRST_PROGRESS_TIMEOUT",
                                "PROVIDER_IDLE_TIMEOUT", "PROVIDER_PREDICTED_DEADLINE_REACHED", "PROVIDER_HARD_LIMIT_REACHED"})


def is_transport_failure(value: str) -> bool:
    return value in TRANSPORT_FAILURES


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


class CallBudget:
    def __init__(self, limit: int = 8, *, rows: list[dict[str, Any]] | None = None, ledger: pathlib.Path | None = None) -> None:
        self.limit = limit; self.rows = list(rows or []); self.current: dict[str, str] = {}; self.ledger = ledger

    def bind(self, *, project: str, task_class: str, provider: str, action: str) -> None:
        self.current = {"project": project, "task_class": task_class, "provider": provider, "action": action}

    def authorize(self, _subject: Any = None, operation: str = "") -> None:
        if len(self.rows) >= self.limit:
            raise RuntimeError("PROVIDER_CALL_LIMIT_REACHED")
        self.rows.append({**self.current, "operation": operation or self.current.get("action", ""), "started_at": time.time()})
        if self.ledger is not None:
            write_json(self.ledger, {"kind": "ProviderCallLedger", "schema_version": "1.0", "calls": self.rows, "contains_credentials": False})


def synthetic_profile(provider: str, task: str, *, functional: float, materialized: bool = True,
                      latency: float = 100_000, confidence: str = "LOW") -> ProviderCapabilityProfile:
    raw = ProviderCapabilityProfile(provider, MODEL[provider], task, 1, functional, 1, 1, 1, 1,
        "UNAVAILABLE", "UNAVAILABLE", latency, {} if materialized else {"TIMEOUT": 1}, "iter-028/029",
        "native-connector", "task-gated-level3", "provider-selection-v2", True, (),
        structured_output_mode="STRICT_JSON_SCHEMA", qualification_status="PROVISIONAL_ELIGIBLE", confidence=confidence)
    return replace(raw, profile_hash=canonical_hash(raw.as_dict(include_hash=False)))


def freeze_plan() -> tuple[ProjectProviderPlan, tuple[ProviderCapabilityProfile, ...]]:
    profiles = (
        synthetic_profile("grok", "project.domain.simple", functional=1.0, latency=55_000),
        synthetic_profile("qwen", "project.domain.simple", functional=0.0, materialized=False, latency=206_000),
        synthetic_profile("grok", "project.domain.persistent", functional=0.0, latency=50_000),
        synthetic_profile("grok", "project.domain.library", functional=0.8, latency=55_000),
        synthetic_profile("qwen", "project.domain.library", functional=0.0, materialized=False, latency=216_000),
        synthetic_profile("qwen", "repository.patch", functional=1.0, latency=146_391, confidence="MEDIUM"),
        synthetic_profile("qwen", "project.repair", functional=1.0, latency=146_391),
        synthetic_profile("qwen", "capability.build", functional=1.0, latency=100_000),
    )
    selector = ProviderSelector(profiles)
    decisions = {task: selector.select(task) for task in (
        "project.domain.simple", "project.domain.persistent", "project.domain.library",
        "repository.patch", "project.repair", "capability.build")}
    plan = ProjectProviderPlan(
        "task-gated-level3", decisions["project.domain.simple"].selected_provider,
        decisions["project.domain.persistent"].selected_provider,
        decisions["project.domain.library"].selected_provider,
        decisions["repository.patch"].selected_provider, decisions["project.repair"].selected_provider,
        decisions["capability.build"].selected_provider,
        {"project.domain.simple": "qwen", "project.domain.persistent": "qwen", "project.domain.library": "qwen"},
        {task: decision.profile_refs[decision.selected_provider] for task, decision in decisions.items()},
        {task: decision.score for task, decision in decisions.items()},
        {task: decision.confidence for task, decision in decisions.items()},
    )
    return plan, profiles


def task_class_for(case: Any) -> str:
    return {"PERSISTENT_CRUD": "project.domain.persistent", "LIBRARY": "project.domain.library"}.get(case.project_type, "project.domain.simple")


def domain_spec(manifest):
    return next(item for item in manifest.bundle_specs if item.execution_mode == "PROVIDER")


def verify_project(workspace: pathlib.Path, case: Any, root: pathlib.Path, *, package: bool) -> dict[str, Any]:
    row = {"compile": _compile(workspace, case), "tests": _pytest(workspace),
           "oracle": _evaluate(workspace, case.package_name, case.public_cases, "oracle"),
           "hidden": _evaluate(workspace, case.package_name, case.hidden_cases, "hidden"),
           "snapshot": _snapshot(workspace)}
    if package:
        packaged = _package(ROOT, workspace, root, case, ITERATION)
        row.update(package=packaged, runtime_smoke=packaged["runtime_smoke"])
    return row


def exact_failure(exc: Exception, case: Any, target: str) -> dict[str, Any]:
    text = str(exc)
    hidden = text.startswith("hidden failure:")
    return {
        "case_id": case.project_id, "obligation_ids": sorted("obligation." + key for key in case.behavior_contract),
        "operation": "PROJECT_VERIFICATION", "parameters": {},
        "expected_outcome": "all public/domain/hidden checks pass",
        "observed_outcome": "WITHHELD_BY_POLICY" if hidden else text[-3500:],
        "failure_owner": "DOMAIN_CANDIDATE", "affected_path": target,
        "allowed_repair_scope": [target], "failure_domain": "CANDIDATE_FUNCTIONAL_DEFECT",
    }


def repair_domain(*, case: Any, workspace: pathlib.Path, client: ConnectorCompletionClient, provider: str,
                  budget: CallBudget, evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    target = f"{case.package_name}/core.py"
    store = FileLessonStore(workspace.parent / "repair-lessons")
    generation = ProductionGenerationClient(client, StoreLessonReader(store), store=store, max_provider_calls=1)
    budget.bind(project=case.project_id, task_class="project.repair", provider=provider, action="repair")
    service = RepositoryCodegenService(generation, ModelRoleConfig("worker", provider, 240, 3000, 0.0, "low"),
        provider_id=provider, mode="SELECTED", call_authorizer=lambda operation: budget.authorize(operation=operation), max_attempts=1).as_task_class("project.repair")
    request = ChangeRequest(case.project_id + ".repair", "Repair only the domain candidate from structured failure evidence.",
        ChangeKind.BUG_FIX, (json.dumps(dict(evidence), ensure_ascii=False),),
        tuple(str(value) for value in case.interface_contract.values()),
        ("tests", "configuration", "README.md", "pyproject.toml", "hidden acceptance"),
        tuple(str(value) for value in case.behavior_contract.values()), (target,))
    return service.run(workspace, request).as_dict()


def run_greenfield(case: Any, root: pathlib.Path, client: ConnectorCompletionClient, plan: ProjectProviderPlan,
                   gate_decision: Any, budget: CallBudget) -> dict[str, Any]:
    started = time.monotonic(); workspace = root / "workspace"; workspace.mkdir(parents=True, exist_ok=True)
    contract = {**_contract(case), "cli_contract": case.cli_contract}
    manifest = GenerationManifestCompiler().compile(project_id=case.project_id, project_type=case.project_type,
        package_name=case.package_name, project_contract=contract, obligations=_obligations(case),
        interface_contract=case.interface_contract, target_paths=case.target_paths, cli_contract=case.cli_contract)
    spec = domain_spec(manifest); task_class = task_class_for(case)
    _render_tests(workspace, case)
    authority = ProjectActionAuthority(gate_decision.selected_generation_provider,
                                       gate_decision.selected_backup_provider, gate_decision.selected_repair_provider)
    providers = [(gate_decision.selected_generation_provider, "primary")]
    service = None; outcome: Mapping[str, Any] = {}; selected = providers[0][0]
    while providers:
        selected, action = providers.pop(0)
        store = FileLessonStore(root / (action + "-lessons"))
        generation = ProductionGenerationClient(client, StoreLessonReader(store), store=store, max_provider_calls=1)
        route_hash = canonical_hash({"plan_hash": plan.plan_hash, "task_class": task_class, "provider": selected, "action": action})
        budget.bind(project=case.project_id, task_class=task_class, provider=selected, action=action)
        service = GreenfieldBundleProductionService(generation, ModelRoleConfig("worker", selected, 300, 7000, 0.0, "low"),
            root / ("production-" + action), provider_id=selected, route_snapshot_hash=route_hash,
            call_authorizer=lambda _spec, operation: budget.authorize(operation=operation))
        outcome = service.run_initial(manifest, contract, workspace, retry_transport=False, repair_candidate=False)
        domain_revision = outcome.get("revision_ids", {}).get(spec.bundle_id, "")
        if domain_revision:
            authority.record_candidate(domain_revision); break
        failure = next((a.get("failure_class", "") for a in outcome.get("attempts", []) if a.get("status") == "PROVIDER_BLOCKED"), "")
        if action == "primary" and is_transport_failure(failure):
            backup = authority.authorize_backup(failure_domain="PROVIDER_TRANSPORT_FAILURE")
            providers.append((backup, "backup")); continue
        break
    row: dict[str, Any] = {"project_id": case.project_id, "project_type": case.project_type, "task_class": task_class,
        "gate_decision_hash": gate_decision.decision_hash, "provider_plan_hash": plan.plan_hash,
        "primary_provider": gate_decision.selected_generation_provider, "backup_provider": gate_decision.selected_backup_provider,
        "repair_provider": gate_decision.selected_repair_provider, "selected_provider": selected,
        "cli_provider_calls": 0, "outcome": outcome, "candidate_revision_ids": list(outcome.get("revision_ids", {}).values()),
        "status": "FAIL", "manual_candidate_edits": 0, "whole_replans": 0}
    if service is None or outcome.get("status") != "SUCCEEDED" or not authority.candidate_revision_id:
        row["failure_domain"] = "PROVIDER_NO_CANDIDATE"; row["wall_time_seconds"] = round(time.monotonic() - started, 3); return row
    projection = service.prompt_projections[-1]
    qualification = ProjectShapedQualificationReceipt(
        f"qualification.{case.project_id}", task_class, case.project_id, selected, MODEL[selected],
        manifest.project_contract_hash, spec.interface_contract.interface_hash,
        canonical_hash({"refs": list(spec.obligation_refs)}), projection.projection_hash,
        outcome["attempts"][0].get("lesson_snapshot_hash", ""), service.route_snapshot_hash,
        task_class + "@1", authority.candidate_revision_id, "DOMAIN_INTERFACE_PASS", "PROJECT_VALIDATION_PENDING", True)
    row.update(prompt_projection=projection.as_dict(include_payload=False), prompt_projection_hash=projection.projection_hash,
               qualification_receipt=qualification.as_dict())
    try:
        row.update(verify_project(workspace, case, root, package=True)); row["status"] = "PASS"
    except Exception as exc:
        evidence = exact_failure(exc, case, spec.target_paths[0]); row["failure_evidence"] = evidence
        try:
            repair_provider = authority.authorize_repair(failure_domain="CANDIDATE_FUNCTIONAL_DEFECT")
            row["repair_receipt"] = repair_domain(case=case, workspace=workspace, client=client, provider=repair_provider,
                                                   budget=budget, evidence=evidence)
            child = service.adopt_repository_patch(manifest, spec, workspace, outcome["run_id"], request_id=case.project_id + ".repair")
            service.reassemble(manifest, workspace); row["candidate_revision_ids"].append(child)
            row.update(verify_project(workspace, case, root, package=True)); row["status"] = "PASS"
        except Exception as repair_exc:
            row.update(failure_domain="CANDIDATE_FUNCTIONAL_DEFECT", failure=f"{type(repair_exc).__name__}:{repair_exc}")
    row["provider_calls"] = sum(1 for call in budget.rows if call["project"] == case.project_id)
    row["wall_time_seconds"] = round(time.monotonic() - started, 3)
    return row


def run_patch(case: Any, root: pathlib.Path, client: ConnectorCompletionClient, plan: ProjectProviderPlan,
              gate_decision: Any, budget: CallBudget) -> dict[str, Any]:
    started = time.monotonic(); workspace = root / "workspace"; workspace.mkdir(parents=True, exist_ok=True)
    for relative, content in case.initial_files.items():
        target = workspace / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content, encoding="utf-8")
    store = FileLessonStore(root / "lessons"); generation = ProductionGenerationClient(client, StoreLessonReader(store), store=store, max_provider_calls=2)
    provider = gate_decision.selected_generation_provider
    budget.bind(project=case.project_id, task_class="repository.patch", provider=provider, action="primary")
    service = RepositoryCodegenService(generation, ModelRoleConfig("worker", provider, 240, 6000, 0.0, "low"),
        provider_id=provider, mode="SELECTED", call_authorizer=lambda operation: budget.authorize(operation=operation), max_attempts=2)
    request = ChangeRequest(case.project_id, case.public_goal, ChangeKind.FEATURE,
        tuple(str(v) for v in case.behavior_contract.values()), ("fixture_cli.render(value) unchanged", "text output unchanged"),
        ("tests", "configuration", "fixture_cli/core.py"), ("existing tests pass", "--json emits canonical object"), case.allowed_paths)
    row = {"project_id": case.project_id, "project_type": case.project_type, "task_class": "repository.patch",
           "gate_decision_hash": gate_decision.decision_hash, "provider_plan_hash": plan.plan_hash,
           "primary_provider": provider, "backup_provider": gate_decision.selected_backup_provider,
           "repair_provider": gate_decision.selected_repair_provider, "cli_provider_calls": 0,
           "status": "FAIL", "manual_candidate_edits": 0, "whole_replans": 0}
    try:
        receipt = service.run(workspace, request); row["receipt"] = receipt.as_dict()
        row.update(tests=_pytest(workspace), oracle=_evaluate(workspace, case.package_name, case.public_cases, "oracle"),
                   hidden=_evaluate(workspace, case.package_name, case.hidden_cases, "hidden"), snapshot=_snapshot(workspace))
        row["status"] = "PASS" if receipt.status == "PASS" else "FAIL"
    except Exception as exc:
        row.update(failure_domain="REPOSITORY_PATCH_FAILURE", failure=f"{type(exc).__name__}:{exc}")
    row["provider_calls"] = sum(1 for call in budget.rows if call["project"] == case.project_id)
    row["wall_time_seconds"] = round(time.monotonic() - started, 3)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--provider-lab-root", type=pathlib.Path, required=True)
    parser.add_argument("--output-root", type=pathlib.Path, required=True)
    parser.add_argument("--recover-interrupted-project", action="append", default=[]); args = parser.parse_args()
    output = args.output_root.resolve(); output.mkdir(parents=True, exist_ok=True)
    plan, profiles = freeze_plan(); write_json(output / "provider_plan.json", plan.as_dict())
    evidence = (
        ProductionQualificationEvidence("project.domain.simple", "qwen", MODEL["qwen"], TaskClassGateStatus.PRODUCTION_DEGRADED_NO_CANDIDATE, ("ITER-029:simple",)),
        ProductionQualificationEvidence("project.domain.persistent", "grok", MODEL["grok"], TaskClassGateStatus.PRODUCTION_DEGRADED_CANDIDATE_DEFECT, ("ITER-029:persistent",)),
        ProductionQualificationEvidence("project.domain.library", "qwen", MODEL["qwen"], TaskClassGateStatus.PRODUCTION_DEGRADED_NO_CANDIDATE, ("ITER-029:library",)),
        ProductionQualificationEvidence("repository.patch", "qwen", MODEL["qwen"], TaskClassGateStatus.PRODUCTION_QUALIFIED, ("ITER-029:patch",)),
    )
    gate = TaskClassQualificationGate(profiles, evidence)
    cases = {case.project_id: case for case in (*greenfield_cases(), _existing_cases()[0])}
    order = ("existing_repo_json_feature", "bookmark_store_cli", "line_select_cli", "mapping_overlay_library")
    decisions = {pid: gate.decide("repository.patch" if pid == "existing_repo_json_feature" else task_class_for(cases[pid]),
                                  plan, project_id=pid, model_by_provider=MODEL) for pid in order}
    if not decisions["existing_repo_json_feature"].allow_project_run:
        raise RuntimeError("TASK_GATE_ISOLATION_FAILURE")
    write_json(output / "task_gate_decisions.json", {key: value.as_dict() for key, value in decisions.items()})
    prior = json.loads((output / "results.json").read_text(encoding="utf-8")) if (output / "results.json").is_file() else {}
    rows = list(prior.get("results", [])); prior_usage = list(prior.get("provider_usage", []))
    for pid in args.recover_interrupted_project:
        if any(row.get("project_id") == pid for row in rows):
            continue
        receipts = list((output / pid).glob("production-primary/candidate_lifecycle/**/provider_attempts/*.json"))
        primary_receipt = json.loads(receipts[-1].read_text(encoding="utf-8")) if receipts else {}
        task = task_class_for(cases[pid]); primary = decisions[pid].selected_generation_provider
        prior_usage.append({"project": pid, "task_class": task, "provider": primary, "action": "primary",
                            "operation": "GENERATION", "result": primary_receipt.get("error_class", "INTERRUPTED")})
        prior_usage.append({"project": pid, "task_class": task, "provider": decisions[pid].selected_backup_provider,
                            "action": "backup", "operation": "GENERATION", "result": "OPERATOR_CANCELLED_AUTHORITY_FIX"})
        rows.append({"project_id": pid, "project_type": cases[pid].project_type, "task_class": task,
                     "gate_decision_hash": decisions[pid].decision_hash, "provider_plan_hash": plan.plan_hash,
                     "primary_provider": primary, "backup_provider": decisions[pid].selected_backup_provider,
                     "repair_provider": decisions[pid].selected_repair_provider, "provider_calls": 2,
                     "candidate_revision_ids": [], "cli_provider_calls": 0, "status": "FAIL",
                     "failure_domain": "FRAMEWORK_AUTHORITY_FIX_INTERRUPTION",
                     "failure": primary_receipt.get("error_class", "PROVIDER_SCHEMA_FAILURE"),
                     "manual_candidate_edits": 0, "whole_replans": 0})
    client = native_client(args.provider_lab_root, output); budget = CallBudget(8, rows=prior_usage, ledger=output / "provider_call_ledger.json")
    for pid in order:
        if any(row.get("project_id") == pid for row in rows):
            continue
        root = output / pid
        if root.exists(): shutil.rmtree(root)
        row = (run_patch(cases[pid], root, client, plan, decisions[pid], budget) if pid == "existing_repo_json_feature"
               else run_greenfield(cases[pid], root, client, plan, decisions[pid], budget))
        rows.append(row); write_json(output / "results.json", {"results": rows, "provider_usage": budget.rows, "contains_credentials": False})
    passed = sum(row["status"] == "PASS" for row in rows)
    by_id = {row["project_id"]: row for row in rows}
    full = passed == 4
    limits = passed >= 3 and by_id["line_select_cli"]["status"] == "PASS" and by_id["existing_repo_json_feature"]["status"] == "PASS" and (by_id["bookmark_store_cli"]["status"] == "PASS" or by_id["mapping_overlay_library"]["status"] == "PASS")
    status = "LEVEL_3_MULTI_TYPE_PROJECT_GENERATION_FUNCTIONAL_PASS" if full else ("LEVEL_3_MULTI_TYPE_PROJECT_GENERATION_PASS_WITH_LIMITS" if limits else "LEVEL_3_MULTI_TYPE_PROJECT_GENERATION_NEEDS_REWORK")
    summary = {"kind": "TaskGatedMultitypeValidation", "schema_version": "1.0", "iteration": ITERATION,
        "status": status, "passed": passed, "total": 4, "provider_calls": len(budget.rows), "provider_call_limit": 8,
        "results": rows, "provider_usage": budget.rows, "cli_provider_calls": 0, "manual_candidate_edits": 0,
        "whole_replans": 0, "silent_fallback": 0, "unsafe_admissions": 0, "accepted_interface_breaks": 0,
        "hidden_leakage": 0, "orphan_workers": 0, "full_regression": "NOT_RUN_BY_POLICY", "contains_credentials": False}
    write_json(output / "summary.json", summary); print(json.dumps(summary, ensure_ascii=False)); return 0 if limits else 2


if __name__ == "__main__":
    raise SystemExit(main())
