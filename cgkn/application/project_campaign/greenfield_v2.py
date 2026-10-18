from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import time
import uuid
from typing import Any, Mapping, Sequence

from cgkn.application.capability_builder import CapabilityBuilderService, CapabilityRisk, CapabilitySpec, CapabilityStore, StoredCapabilityRuntime
from cgkn.application.learning import ProductionGenerationClient
from cgkn.application.repository_codegen import ChangeKind, ChangeRequest, RepositoryCodegenService
from cgkn.application.self_growth import SelfGrowthService
from cgkn.application.software_project.greenfield import CampaignBudgetAllocator, GenerationManifestCompiler, GreenfieldBundleProductionService, canonical_hash
from cgkn.execution.contracts import utc_now
from cgkn.providers import ModelRoleConfig

from .contracts import ProjectCase
from .matrix import campaign_matrix
from .service import LICENSE_CAP, PYPROJECT_CAP, README_CAP, _capability_input, _compile, _contract, _evaluate, _obligations, _package, _pytest, _render_tests, _snapshot, _write_json


CAMPAIGN_ID = "ITER-GREENFIELD-BUNDLE-GENERATION-027"
API_DOCS_CAP = "project.docs.api_reference.render@1"


class ProjectStageFailure(RuntimeError):
    def __init__(self, stage: str, owner: str, failure_code: str) -> None:
        super().__init__(f"{stage}:{failure_code}")
        self.stage, self.owner, self.failure_code = stage, owner, failure_code


def targeted_cases() -> tuple[ProjectCase, ...]:
    wanted = {"text_stats_cli", "todo_json_cli", "zip_manifest_cli", "notes_search_cli"}
    return tuple(case for case in campaign_matrix() if case.project_id in wanted)


def existing_repo_canary() -> ProjectCase:
    return next(case for case in campaign_matrix() if case.project_id == "existing_repo_path_bug")


def mini_campaign_cases() -> tuple[ProjectCase, ...]:
    by_id = {case.project_id: case for case in campaign_matrix()}
    rows = [by_id[name] for name in ("json_flatten_cli", "ini_merge_cli", "duplicate_finder_cli", "env_audit_cli")]
    rows.extend((_csv_profile_case(), _config_overlay_case(), by_id["rename_plan_cli"], by_id["log_summary_library"]))
    return tuple(rows)


class GreenfieldV2Campaign:
    def __init__(self, repository_root: pathlib.Path | str, artifact_root: pathlib.Path | str,
                 generation: ProductionGenerationClient, model_config: ModelRoleConfig,
                 *, source_commit: str, previous_capability_store: pathlib.Path | str | None = None) -> None:
        self.repository_root = pathlib.Path(repository_root).resolve(); self.root = pathlib.Path(artifact_root).resolve()
        self.generation, self.config, self.source_commit = generation, model_config, source_commit
        self.root.mkdir(parents=True, exist_ok=True)
        self.budget = CampaignBudgetAllocator(); self.compiler = GenerationManifestCompiler()
        self.capability_store = CapabilityStore(self.root / "capability_registry")
        if previous_capability_store:
            self._seed_capabilities(pathlib.Path(previous_capability_store))
        self.receipts: list[dict[str, Any]] = []

    def run_cases(self, cases: Sequence[ProjectCase], *, phase: str, partition: str) -> tuple[dict[str, Any], ...]:
        rows = []
        for case in cases:
            row = self.run_greenfield(case, phase=phase, partition=partition)
            rows.append(row); self.receipts.append(row)
        return tuple(rows)

    def run_greenfield(self, case: ProjectCase, *, phase: str, partition: str) -> dict[str, Any]:
        started = time.perf_counter(); project_root = self.root / "projects" / case.project_id
        workspace = project_root / "workspace"; workspace.mkdir(parents=True, exist_ok=True)
        run_id = f"{case.project_id}-{uuid.uuid4().hex[:10]}"
        project_contract = _contract(case); obligations = _obligations(case)
        manifest = self.compiler.compile(project_id=case.project_id, project_type=case.project_type, package_name=case.package_name,
                                         project_contract=project_contract, obligations=obligations,
                                         interface_contract=case.interface_contract, target_paths=case.target_paths)
        _write_json(project_root / "generation_manifest.json", manifest.as_dict())
        _render_tests(workspace, case)
        required = list(case.required_capabilities)
        if case.project_id == "config_overlay_library" and API_DOCS_CAP not in required:
            required.append(API_DOCS_CAP)
        grown, reused = self._resolve_capabilities(case, tuple(required))
        before_calls = self.generation.provider_call_count
        service = GreenfieldBundleProductionService(
            self.generation, self.config, project_root / "greenfield_v2",
            route_snapshot_hash=canonical_hash({"provider": "grok", "mode": "SINGLE_PROVIDER_MODE", "fallback": "deny"}),
            call_authorizer=lambda _spec, _operation: self.budget.consume(partition, case.project_id),
        )
        outcome = service.run_initial(manifest, project_contract, workspace, run_id=run_id)
        repair_calls = 0; failure_domain = ""
        tests: Mapping[str, Any] = {}; oracle: Mapping[str, Any] = {}; hidden: Mapping[str, Any] = {}; package: Mapping[str, Any] = {}; smoke: Mapping[str, Any] = {}
        try:
            if outcome["status"] != "SUCCEEDED":
                failure_domain = self._bundle_failure(outcome)
                raise RuntimeError(failure_domain)
            self._render_deterministic_assets(workspace, case, tuple(required))
            tests, oracle, hidden, package, smoke = self._validate_and_package(workspace, project_root, case)
        except Exception as first_error:
            remaining = self.budget.snapshot()["partitions"][partition]["remaining"]
            if outcome["status"] == "SUCCEEDED" and remaining > 0 and self.generation.provider_call_count - before_calls < 3:
                owner = self._owner_bundle(manifest, first_error)
                try:
                    patch = self._repair_bridge(case, workspace, owner, partition)
                    repair_calls = patch.calls
                    if patch.status != "PASS" or patch.interface_breaks:
                        raise RuntimeError("INTERFACE_AUTHORITY_VIOLATION" if patch.interface_breaks else "PROJECT_REPAIR_FAILED")
                    service.adopt_repository_patch(manifest, owner, workspace, run_id, request_id="repository.patch@1")
                    service.reassemble(manifest, workspace)
                    tests, oracle, hidden, package, smoke = self._validate_and_package(workspace, project_root, case)
                    failure_domain = ""
                except Exception as repair_error:
                    failure_domain = self._classify_failure(repair_error, owner.bundle_kind.value)
            elif not failure_domain:
                failure_domain = self._classify_failure(first_error, "FRAMEWORK")
        calls = self.generation.provider_call_count - before_calls
        attempts = [item.as_dict() for item in service.attempts]
        status = "PASS" if package.get("status") == "PASS" and not failure_domain else "FAIL"
        receipt = {
            "kind": "GreenfieldV2ProjectReceipt", "schema_version": "1.0", "project_id": case.project_id,
            "phase": phase, "project_type": case.project_type, "manifest_hash": manifest.manifest_hash,
            "bundle_specs": [item.as_dict() for item in manifest.bundle_specs], "bundle_revision_ids": dict(service.current_revisions),
            "bundle_calls": len(attempts), "bundle_retries": sum(item["status"] == "PROVIDER_BLOCKED" for item in attempts),
            "repair_bridge_calls": repair_calls,
            "lesson_snapshots": {item["bundle_id"]: item["lesson_snapshot_hash"] for item in attempts if item["lesson_snapshot_hash"]},
            "required_capabilities": required, "grown_capabilities": grown, "reused_capabilities": reused,
            "reused_nodes": [], "rerun_nodes": [], "tests": tests, "oracle": oracle, "hidden": hidden,
            "snapshot": _snapshot(workspace) if status == "PASS" else {}, "package": package, "runtime_smoke": smoke,
            "failure_domain": failure_domain, "final_status": status, "provider_calls": calls,
            "provider_attempts": attempts, "source_commit": self.source_commit,
            "wall_time_seconds": round(time.perf_counter() - started, 3), "manual_candidate_edits": 0,
            "whole_project_replans": 0, "unsafe_admissions": 0, "accepted_interface_breaks": 0,
            "hidden_leakage": 0, "contains_credentials": False,
        }
        _write_json(project_root / "project_receipt.json", receipt)
        return receipt

    def run_existing_canary(self, case: ProjectCase) -> dict[str, Any]:
        root = self.root / "projects" / case.project_id; workspace = root / "workspace"; workspace.mkdir(parents=True, exist_ok=True)
        for relative, content in case.initial_files.items():
            path = workspace / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")
        _render_tests(workspace, case)
        request = ChangeRequest(case.project_id, case.public_goal, ChangeKind.BUG_FIX, tuple(str(item) for item in case.behavior_contract.values()), ("public interfaces unchanged",), ("tests", "metadata", "governance", "hidden acceptance"), ("public and hidden cases",), case.allowed_paths)
        service = RepositoryCodegenService(self.generation, self._repair_config(), provider_id="grok", mode="SINGLE_PROVIDER_MODE", call_authorizer=lambda _operation: self.budget.consume("FRAMEWORK_CANARY", case.project_id), max_attempts=2)
        receipt = service.run(workspace, request)
        oracle = _evaluate(workspace, case.package_name, case.public_cases, "oracle") if receipt.status == "PASS" else {}
        hidden = _evaluate(workspace, case.package_name, case.hidden_cases, "hidden") if receipt.status == "PASS" else {}
        row = {"kind": "ExistingRepoCanaryReceipt", "schema_version": "1.0", "project_id": case.project_id, "status": "PASS" if receipt.status == "PASS" and oracle and hidden else "FAIL", "patch": receipt.as_dict(), "oracle": oracle, "hidden": hidden, "snapshot": _snapshot(workspace), "contains_credentials": False}
        _write_json(root / "project_receipt.json", row); return row

    def freeze_holdout(self, cases: Sequence[ProjectCase]) -> Mapping[str, Any]:
        lesson_index = self.root / "lessons" / "lesson_index.json"
        value = {"kind": "GreenfieldV2HoldoutFreeze", "schema_version": "1.0", "source_commit": self.source_commit,
                 "lesson_snapshot_hash": canonical_hash(json.loads(lesson_index.read_text())) if lesson_index.is_file() else "",
                 "provider_route": {"provider": "grok", "mode": "SINGLE_PROVIDER_MODE", "fallback": "deny"},
                 "manifest_version": self.compiler.VERSION, "bundle_policy_version": "1.0", "budget_policy_version": "1.0",
                 "cases": [{"project_id": case.project_id, "case_hash": case.case_hash, "hidden_hash": case.hidden_hash} for case in cases],
                 "frozen_at": utc_now(), "contains_credentials": False}
        return _write_json(self.root / "holdout_freeze.json", value)

    def summary(self) -> Mapping[str, Any]:
        rows = self.receipts; passed = sum(row["final_status"] == "PASS" for row in rows)
        attempts = [item for row in rows for item in row.get("provider_attempts", ())]
        transport = sum(item.get("status") == "PROVIDER_BLOCKED" for item in attempts)
        return {"kind": "GreenfieldV2CampaignSummary", "schema_version": "1.0", "campaign_id": CAMPAIGN_ID,
                "source_commit": self.source_commit, "total": len(rows), "passed": passed, "failed": len(rows) - passed,
                "transport_failures": transport, "provider_calls": sum(row.get("provider_calls", 0) for row in rows),
                "budget": self.budget.snapshot(), "projects": rows, "full_regression": "NOT_RUN_BY_POLICY", "contains_credentials": False}

    def _resolve_capabilities(self, case: ProjectCase, required: tuple[str, ...]) -> tuple[list[str], list[str]]:
        grown: list[str] = []; reused: list[str] = []
        for ref in required:
            slug = ref.replace("@", "-").replace(".", "-")
            if (self.capability_store.root / slug / "admission.json").is_file():
                reused.append(ref); continue
            if ref != API_DOCS_CAP:
                raise RuntimeError("CAPABILITY_GAP:" + ref)
            before = self.generation.provider_call_count
            growth = SelfGrowthService(CapabilityBuilderService(self.generation, self.config, provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=self.capability_store), self.capability_store, provider_id="grok", mode="SINGLE_PROVIDER_MODE", history_path=self.root / "api_docs_growth_history.json")
            outcome = growth.ensure_and_resume(self.root / "growth" / "api-docs", _api_docs_spec(), {"package": case.package_name, "public_interfaces": [dict(case.interface_contract)]})
            calls = self.generation.provider_call_count - before
            if calls: self.budget.consume("SELF_GROWTH_RESERVE", case.project_id, calls=calls)
            if outcome.status != "PASS": raise RuntimeError("CAPABILITY_IMPLEMENTATION_BLOCKER:" + outcome.failure_class)
            grown.append(ref)
        return grown, reused

    def _render_deterministic_assets(self, workspace: pathlib.Path, case: ProjectCase, required: tuple[str, ...]) -> None:
        runtime = StoredCapabilityRuntime(self.capability_store, provider_id="grok")
        value = runtime.invoke(PYPROJECT_CAP, _capability_input(PYPROJECT_CAP, case)); (workspace / "pyproject.toml").write_text(str(value["pyproject_toml"]), encoding="utf-8")
        if README_CAP in required:
            value = runtime.invoke(README_CAP, _capability_input(README_CAP, case)); (workspace / "README.md").write_text(str(value["readme_md"]), encoding="utf-8")
        else: (workspace / "README.md").write_text(f"# {case.project_id}\n\n{case.public_goal}\n\n`python -m {case.package_name} --help`\n", encoding="utf-8")
        if LICENSE_CAP in required:
            value = runtime.invoke(LICENSE_CAP, _capability_input(LICENSE_CAP, case)); (workspace / "LICENSE").write_text(str(value["license_text"]), encoding="utf-8")
        if API_DOCS_CAP in required:
            value = runtime.invoke(API_DOCS_CAP, {"package": case.package_name, "public_interfaces": [dict(case.interface_contract)]}); (workspace / "API_REFERENCE.md").write_text(str(value["markdown"]), encoding="utf-8")

    def _validate_and_package(self, workspace: pathlib.Path, root: pathlib.Path, case: ProjectCase):
        try: _compile(workspace, case)
        except Exception as exc: raise ProjectStageFailure("COMPILE", "DOMAIN", "SOURCE_COMPILE_FAILED") from exc
        try: tests = _pytest(workspace)
        except Exception as exc: raise ProjectStageFailure("PYTEST", self._failure_owner(str(exc)), "PUBLIC_CONTRACT_FAILED") from exc
        try: oracle = _evaluate(workspace, case.package_name, case.public_cases, "oracle")
        except Exception as exc: raise ProjectStageFailure("ORACLE", self._failure_owner(str(exc)), "PUBLIC_ORACLE_FAILED") from exc
        try: hidden = _evaluate(workspace, case.package_name, case.hidden_cases, "hidden")
        except Exception as exc: raise ProjectStageFailure("HIDDEN", self._failure_owner(str(exc)), "WITHHELD_ACCEPTANCE_FAILED") from exc
        help_result = subprocess.run(["python", "-m", case.package_name, "--help"], cwd=workspace, capture_output=True, text=True, timeout=30)
        if help_result.returncode or "usage" not in help_result.stdout.lower() or "traceback" in help_result.stderr.lower(): raise ProjectStageFailure("CLI_HELP", "CLI", "CLI_HELP_CONTRACT_FAILED")
        try: package = _package(self.repository_root, workspace, root, case, self.source_commit)
        except Exception as exc: raise ProjectStageFailure("PACKAGE", "DETERMINISTIC", "PROJECT_PACKAGE_FAILED") from exc
        return tests, oracle, hidden, package, package.get("runtime_smoke", {})

    def _repair_bridge(self, case: ProjectCase, workspace: pathlib.Path, owner, partition: str):
        frozen = owner.interface_contract.as_dict()
        requirements = tuple(str(item) for item in case.behavior_contract.values()) + ("Implement the frozen bundle interface exactly: " + json.dumps(frozen, sort_keys=True),)
        request = ChangeRequest(f"{case.project_id}-{owner.bundle_kind.value.lower()}-repair", "Repair the evidenced project defect. Controlled CLI errors must use exact exit code 2 and stderr. Do not change frozen public interfaces.", ChangeKind.BUG_FIX, requirements, ("frozen bundle interface", "CLI help contract", "controlled error exit code 2"), ("tests", "metadata", "governance", "hidden acceptance", "public interface changes"), ("compile", "pytest", "oracle", "CLI help", "controlled errors exit code 2"), owner.target_paths)
        service = RepositoryCodegenService(self.generation, self._repair_config(), provider_id="grok", mode="SINGLE_PROVIDER_MODE", call_authorizer=lambda _operation: self.budget.consume(partition, case.project_id), max_attempts=1)
        return service.run(workspace, request)

    def _seed_capabilities(self, source: pathlib.Path) -> None:
        if not source.is_dir(): return
        self.capability_store.root.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            target = self.capability_store.root / child.name
            if child.is_dir() and not target.exists(): shutil.copytree(child, target)

    @staticmethod
    def _owner_bundle(manifest, failure: Exception):
        owner = str(getattr(failure, "owner", ""))
        if owner == "CLI": return manifest.bundle_specs[1]
        return manifest.bundle_specs[0]

    @staticmethod
    def _failure_owner(text: str) -> str:
        lowered = text.lower()
        return "CLI" if any(token in lowered for token in ("returncode", "exit code", "stdout", "stderr", "argparse", "usage")) else "DOMAIN"

    @staticmethod
    def _bundle_failure(outcome: Mapping[str, Any]) -> str:
        return "PROVIDER_TRANSPORT_FAILURE" if any(item.get("status") == "PROVIDER_BLOCKED" for item in outcome.get("attempts", ())) else "BUNDLE_CANDIDATE_DEFECT"

    @staticmethod
    def _classify_failure(error: Exception, owner: str) -> str:
        text = str(error).lower()
        if "interface_authority" in text: return "BUNDLE_INTERFACE_DEFECT"
        if "package" in text: return "PROJECT_PACKAGE_DEFECT"
        if "hidden" in text: return "PROJECT_HIDDEN_DEFECT"
        if "oracle" in text: return "PROJECT_ORACLE_DEFECT"
        if "pytest" in text: return "PROJECT_TEST_DEFECT"
        if "compile" in text or "syntax" in text: return "PROJECT_COMPILE_DEFECT"
        return f"BUNDLE_CANDIDATE_DEFECT:{owner}"

    @staticmethod
    def _repair_config() -> ModelRoleConfig:
        return ModelRoleConfig("worker", "grok", 180, 1200, 0.0, "low")


def _api_docs_spec() -> CapabilitySpec:
    example_input = {"package": "sample", "public_interfaces": [{"public_api": "sample.run(value)"}]}
    example_output = {"markdown": "# sample API Reference\n\n## Public interfaces\n\n- `sample.run(value)`\n"}
    return CapabilitySpec("project.docs.api_reference.render", "1", "Render deterministic Markdown API reference from frozen public interfaces.", {"type": "object"}, {"type": "object"}, ({"input": example_input, "output": example_output},), ("result has only markdown", "contains package and every public interface", "deterministic output"), CapabilityRisk.PURE)


def _csv_profile_case() -> ProjectCase:
    return ProjectCase("csv_column_profile_cli", "B", "GREENFIELD_CLI", "csv_column_profile", "Profile CSV columns deterministically.", {"entrypoint": "python -m csv_column_profile", "commands": ["INPUT", "INPUT --json"], "stderr_errors": True, "no_aliases": True}, {"stdlib": "csv", "header": "first row required", "fields": ["name", "row_count", "empty_count", "unique_count"], "malformed_row": "nonzero stderr", "deterministic": True}, ("csv_column_profile/__init__.py", "csv_column_profile/__main__.py", "csv_column_profile/core.py"), ({"files": {"x.csv": "name,age\nAda,3\n,3\n"}, "steps": [{"argv": ["x.csv", "--json"], "code": 0, "json": [{"name": "name", "row_count": 2, "empty_count": 1, "unique_count": 2}, {"name": "age", "row_count": 2, "empty_count": 0, "unique_count": 1}]}]},), ({"files": {"bad.csv": "a,b\n1\n"}, "steps": [{"argv": ["bad.csv"], "code": 2, "stderr_nonempty": True}]},))


def _config_overlay_case() -> ProjectCase:
    return ProjectCase("config_overlay_library", "B", "LIBRARY", "config_overlay", "Merge JSON object layers without mutating inputs.", {"entrypoint": "python -m config_overlay", "commands": ["OUTPUT INPUT1 INPUT2 ..."], "public_api": "config_overlay.merge_layers(layers)", "stderr_errors": True, "no_aliases": True}, {"public_api": "config_overlay.merge_layers(layers)", "objects": "recursive merge", "arrays_scalars": "replace", "inputs": "not mutated", "output": "new object sorted-key deterministic JSON"}, ("config_overlay/__init__.py", "config_overlay/__main__.py", "config_overlay/core.py"), ({"files": {"a.json": "{\"x\":{\"a\":1},\"v\":[1]}", "b.json": "{\"x\":{\"b\":2},\"v\":[2]}"}, "steps": [{"argv": ["out.json", "a.json", "b.json"], "code": 0, "file_json": {"path": "out.json", "value": {"x": {"a": 1, "b": 2}, "v": [2]}}}]},), ({"python": "from config_overlay import merge_layers; a={'x':{'a':1}}; r=merge_layers([a,{'x':{'b':2}}]); assert a=={'x':{'a':1}} and r=={'x':{'a':1,'b':2}}", "code": 0},), (PYPROJECT_CAP, API_DOCS_CAP))
