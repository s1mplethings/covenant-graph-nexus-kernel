from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from cgkn.application.software_project.scope import ScopedFileTransaction, ScopeViolation
from cgkn.executors.llm import WORKER_SCHEMA, validate_worker_proposal
from cgkn.providers import CompletionClient, ModelRoleConfig, parse_json_object
from cgkn.application.learning import GenerationRequest, ProductionGenerationClient, default_production_client

from .csv import compile_csv_cleaner
from .execution import _ScopeAdapter, validate_dependency_actions
from .receipt import write_obligation_preflight
from .work_unit import compile_csv_work_units


@dataclass(frozen=True)
class DirectAgentResult:
    status: str
    run_id: str
    workspace: pathlib.Path
    provider_calls: int
    tokens: int
    wall_time_ms: int
    repair_rounds: int
    hidden_acceptance: str
    manual_edits: int = 0
    whole_replans: int = 0
    public_pytest: str = "FAIL"
    oracle_status: str = "NOT_EVALUATED"
    oracle_evidence: tuple[Mapping[str, Any], ...] = ()
    repair_owners: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": "DIRECT_AGENT", "status": self.status, "run_id": self.run_id,
            "workspace": str(self.workspace), "provider_calls": self.provider_calls, "tokens": self.tokens,
            "wall_time_ms": self.wall_time_ms, "repair_rounds": self.repair_rounds,
            "hidden_acceptance": self.hidden_acceptance, "manual_edits": self.manual_edits,
            "whole_replans": self.whole_replans, "public_pytest": self.public_pytest,
            "oracle_status": self.oracle_status, "oracle_evidence": [dict(item) for item in self.oracle_evidence],
            "repair_owners": list(self.repair_owners),
        }


class DirectAgentService:
    """One bounded high-capability project edit followed by non-bypassable gates."""

    TARGETS = ("csv_cleaner/__init__.py", "csv_cleaner/__main__.py", "csv_cleaner/core.py", "README.md")

    def __init__(self, repository_root: pathlib.Path, client: CompletionClient | ProductionGenerationClient, agent: ModelRoleConfig):
        if agent.role != "agent":
            raise ValueError("direct execution requires an agent role")
        self.generation = client if isinstance(client, ProductionGenerationClient) else default_production_client(client)
        self.root, self.client, self.agent = repository_root.resolve(), self.generation.client, agent

    def run_csv(self, workspace: pathlib.Path, run_root: pathlib.Path) -> DirectAgentResult:
        started = time.perf_counter(); run_id = f"csv-direct-{uuid.uuid4().hex[:10]}"
        workspace, run_root = workspace.resolve(), run_root.resolve()
        workspace.mkdir(parents=True, exist_ok=True); run_root.mkdir(parents=True, exist_ok=True)
        compilation = compile_csv_cleaner()
        from cgkn.application.verification import (
            ContractTestCompiler, ContractTestRenderer, ContractTestValidator,
            EvidenceComparator, OracleEvidence, OracleExecutor, OraclePlanCompiler,
            OracleStatus, PublicTestEvidence, PublicTestStatus,
        )
        if compilation.preflight.as_dict()["status"] != "COMPLETE":
            raise ValueError("obligation preflight must be COMPLETE before Provider execution")
        write_obligation_preflight(run_root / "obligation_preflight.json", compilation.preflight)
        prompt = {
            "node_id": "DIRECT-AGENT",
            "strategy": "DIRECT_AGENT",
            "obligations": compilation.obligations.as_dict(),
            "dependency_policy": next(item.dependency_policy.as_dict() for item in compilation.obligations.obligations if item.dependency_policy),
            "work_unit_contracts": [item.as_dict() for item in compile_csv_work_units(compilation) if item.work_unit_id != "WU-TESTS"],
            "target_paths": list(self.TARGETS),
            "rule": "write the complete bounded project; do not add requirements or dependencies",
        }
        policy = next(item.dependency_policy for item in compilation.obligations.obligations if item.dependency_policy)
        oracle_plan = OraclePlanCompiler().compile_csv(compilation.obligations, policy)
        units = {item.work_unit_id: item for item in compile_csv_work_units(compilation) if item.work_unit_id != "WU-TESTS"}
        provider_calls = 0
        tokens = 0
        repair_rounds = 0
        repair_owners: list[str] = []

        def apply_provider(request: Mapping[str, Any], targets: tuple[str, ...]) -> None:
            nonlocal provider_calls, tokens
            generated = self.generation.generate(GenerationRequest(
                task_class="project.direct", operation="REPAIR" if request.get("repair_round") else "GENERATION",
                project_id="csv_cleaner", capability_ref="agent.direct.project@1", provider_id=self.agent.model,
                system=("You are the bounded high-capability Direct Agent. Implement or repair only the declared scope from canonical obligations and WorkUnit contracts. "
                        "Use supplied failure evidence and current sources. Do not inspect hidden acceptance, add behavior, change policy, or claim validation. Return JSON actions only."),
                goal=dict(request), contract={"obligations": request.get("obligations", {}), "work_units": request.get("work_unit_contracts", [])},
                state=request.get("current_sources", {}), failure_evidence=request.get("failure_evidence", {}),
                schema_name="cgkn_direct_agent_execute", schema=WORKER_SCHEMA, model_config=self.agent,
                dependency_risk_policy=request.get("dependency_policy", {}), allowed_actions=("write_file", "patch_file", "read_file"),
                forbidden_actions=("hidden_acceptance", "policy_change", "contract_change"), run_id=run_id,
            ))
            completion = generated.completion
            provider_calls += 1
            tokens += int(completion.usage.get("total_tokens", 0))
            proposal = validate_worker_proposal(parse_json_object(completion.text), "DIRECT-AGENT")
            if proposal["needs_escalation"]:
                raise ScopeViolation(proposal["escalation_reason"] or "direct agent escalation")
            validate_dependency_actions(workspace, proposal["actions"], policy)
            scope = _ScopeAdapter(targets, targets, (".git", ".github", ".cgkn", "benchmarks", "artifacts", "governance", "cgkn"))
            ScopedFileTransaction(workspace, scope).apply(proposal["actions"])

        apply_provider(prompt, self.TARGETS)
        contract_plan = ContractTestCompiler().compile(compilation.obligations, oracle_plan, policy)
        contract_artifact = ContractTestRenderer().render(contract_plan, policy)
        contract_validation = ContractTestValidator().validate(
            contract_plan, contract_artifact.manifest, contract_artifact.source,
            compilation.obligations, oracle_plan, policy,
        )
        if contract_validation.status != "PASS":
            raise ValueError("contract test validation failed: " + ",".join(contract_validation.errors))
        contract_target = workspace / contract_artifact.path
        contract_target.parent.mkdir(parents=True, exist_ok=True)
        contract_target.write_text(contract_artifact.source, encoding="utf-8")
        (workspace / "tests" / "contract_test_manifest.json").write_text(
            json.dumps(contract_artifact.manifest.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        gate_env = os.environ.copy(); gate_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        commands = (
            [sys.executable, "-m", "compileall", "-q", "."],
            [sys.executable, "-m", "pytest", "-q"],
            [sys.executable, "-m", "csv_cleaner", "--help"],
        )
        all_obligations = tuple(item.obligation_id for item in compilation.obligations.obligations)
        while True:
            gate_results = tuple(subprocess.run(command, cwd=workspace, capture_output=True, timeout=60, env=gate_env) for command in commands)
            public_pytest = "PASS" if gate_results[1].returncode == 0 else "FAIL"
            oracle_rows = OracleExecutor((policy,)).execute_plan(oracle_plan, workspace)
            oracle_status = "PASS" if all(item.status is OracleStatus.PASS for item in oracle_rows) else "FAIL"
            if all(item.returncode == 0 for item in gate_results) and oracle_status == "PASS":
                break
            if repair_rounds >= 2:
                break
            test_asset_obligations = {"OBL-CSV-PUBLIC-TESTS", "OBL-CSV-TEST-PYTEST"}
            selected = next((item for item in oracle_rows if item.status is not OracleStatus.PASS and not set(item.obligation_ids) <= test_asset_obligations), None)
            if selected is None and public_pytest == "PASS":
                selected = next((item for item in oracle_rows if item.status is not OracleStatus.PASS), None)
            if selected is None:
                selected = next((item for item in oracle_rows if not set(item.obligation_ids) <= test_asset_obligations), None)
            if selected is None:
                break
            pytest_stdout = gate_results[1].stdout.decode(errors="replace")
            pytest_stderr = gate_results[1].stderr.decode(errors="replace")
            setup_failed = "ERROR collecting" in pytest_stdout or "fixture" in (pytest_stdout + pytest_stderr).lower()
            public = PublicTestEvidence(
                f"EVIDENCE-DIRECT-PYTEST-{repair_rounds}",
                PublicTestStatus.PASS if public_pytest == "PASS" else PublicTestStatus.FAIL,
                all_obligations, ("PUBLIC-PYTEST",), return_code=gate_results[1].returncode,
                stdout_summary=pytest_stdout[-2000:], stderr_summary=pytest_stderr[-2000:],
                setup_status="FAIL" if setup_failed else "PASS",
                evidence_authority="CANONICAL_CONTRACT",
            )
            failure = EvidenceComparator().compare(selected, public, dependency_policy=policy)
            owner = failure.effective_owner
            if owner is None or owner not in units:
                break
            repair_owners.append(owner)
            unit = units[owner]
            current_sources = {
                path: (workspace / path).read_text(encoding="utf-8")
                for path in unit.target_paths if (workspace / path).is_file()
            }
            repair_prompt = prompt | {
                "repair_round": repair_rounds + 1,
                "repair_owner": owner,
                "target_paths": list(unit.target_paths),
                "work_unit_contracts": [unit.as_dict()],
                "failure_evidence": failure.as_dict(),
                "current_sources": current_sources,
                "rule": "repair only the attributed WorkUnit scope; preserve every other file",
            }
            apply_provider(repair_prompt, unit.target_paths)
            repair_rounds += 1
        passed = all(item.returncode == 0 for item in gate_results)
        env = os.environ.copy()
        env.update({"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "CGKN_GENERATED_PROJECT": str(workspace), "PYTHONPATH": str(workspace), "CGKN_TEST_ALLOWED_PACKAGES": "pytest"})
        hidden_run = subprocess.run([sys.executable, "-m", "pytest", "-q", str(self.root / "benchmarks" / "real_project_generation" / "acceptance" / "test_cli_csv_cleaner.py")], cwd=workspace, capture_output=True, timeout=60, env=env)
        hidden = "PASS" if hidden_run.returncode == 0 else "FAIL"
        status = "PASS" if passed and oracle_status == "PASS" and hidden == "PASS" else "FAIL"
        return DirectAgentResult(
            status, run_id, workspace, provider_calls, tokens,
            int((time.perf_counter() - started) * 1000), repair_rounds, hidden,
            public_pytest=public_pytest, oracle_status=oracle_status,
            oracle_evidence=tuple(item.as_dict() for item in oracle_rows),
            repair_owners=tuple(repair_owners),
        )
