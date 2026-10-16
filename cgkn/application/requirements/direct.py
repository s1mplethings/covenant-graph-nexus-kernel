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

from .csv import compile_csv_cleaner
from .execution import _ScopeAdapter, validate_dependency_actions
from .receipt import write_obligation_preflight
from .test_plan import TestPlanCompiler
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": "DIRECT_AGENT", "status": self.status, "run_id": self.run_id,
            "workspace": str(self.workspace), "provider_calls": self.provider_calls, "tokens": self.tokens,
            "wall_time_ms": self.wall_time_ms, "repair_rounds": self.repair_rounds,
            "hidden_acceptance": self.hidden_acceptance, "manual_edits": self.manual_edits,
            "whole_replans": self.whole_replans,
        }


class DirectAgentService:
    """One bounded high-capability project edit followed by non-bypassable gates."""

    TARGETS = ("csv_cleaner/__init__.py", "csv_cleaner/__main__.py", "csv_cleaner/core.py", "tests/test_csv_cleaner.py", "README.md")

    def __init__(self, repository_root: pathlib.Path, client: CompletionClient, agent: ModelRoleConfig):
        if agent.role != "agent":
            raise ValueError("direct execution requires an agent role")
        self.root, self.client, self.agent = repository_root.resolve(), client, agent

    def run_csv(self, workspace: pathlib.Path, run_root: pathlib.Path) -> DirectAgentResult:
        started = time.perf_counter(); run_id = f"csv-direct-{uuid.uuid4().hex[:10]}"
        workspace, run_root = workspace.resolve(), run_root.resolve()
        workspace.mkdir(parents=True, exist_ok=True); run_root.mkdir(parents=True, exist_ok=True)
        compilation = compile_csv_cleaner()
        if compilation.preflight.as_dict()["status"] != "COMPLETE":
            raise ValueError("obligation preflight must be COMPLETE before Provider execution")
        write_obligation_preflight(run_root / "obligation_preflight.json", compilation.preflight)
        prompt = {
            "node_id": "DIRECT-AGENT",
            "strategy": "DIRECT_AGENT",
            "obligations": compilation.obligations.as_dict(),
            "dependency_policy": next(item.dependency_policy.as_dict() for item in compilation.obligations.obligations if item.dependency_policy),
            "test_plan": TestPlanCompiler().compile(compilation.obligations).as_dict(),
            "work_unit_contracts": [item.as_dict() for item in compile_csv_work_units(compilation)],
            "target_paths": list(self.TARGETS),
            "rule": "write the complete bounded project; do not add requirements or dependencies",
        }
        completion = self.client.complete(
            system=("You are the bounded high-capability Direct Agent. Implement the complete project from canonical obligations and WorkUnit contracts. "
                    "Write only declared target paths. Do not inspect hidden acceptance, add behavior, change policy, or claim validation. Return JSON actions only."),
            user=json.dumps(prompt, ensure_ascii=False, sort_keys=True), schema_name="cgkn_direct_agent_execute", schema=WORKER_SCHEMA,
            config=self.agent,
        )
        proposal = validate_worker_proposal(parse_json_object(completion.text), "DIRECT-AGENT")
        if proposal["needs_escalation"]:
            raise ScopeViolation(proposal["escalation_reason"] or "direct agent escalation")
        policy = next(item.dependency_policy for item in compilation.obligations.obligations if item.dependency_policy)
        validate_dependency_actions(workspace, proposal["actions"], policy)
        scope = _ScopeAdapter(self.TARGETS, self.TARGETS, (".git", ".github", ".cgkn", "benchmarks", "artifacts", "governance", "cgkn"))
        ScopedFileTransaction(workspace, scope).apply(proposal["actions"])
        commands = (
            [sys.executable, "-m", "compileall", "-q", "."],
            [sys.executable, "-m", "pytest", "-q"],
            [sys.executable, "-m", "csv_cleaner", "--help"],
        )
        gate_env = os.environ.copy(); gate_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        passed = all(subprocess.run(command, cwd=workspace, capture_output=True, timeout=60, env=gate_env).returncode == 0 for command in commands)
        env = os.environ.copy()
        env.update({"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "CGKN_GENERATED_PROJECT": str(workspace), "PYTHONPATH": str(workspace), "CGKN_TEST_ALLOWED_PACKAGES": "pytest"})
        hidden_run = subprocess.run([sys.executable, "-m", "pytest", "-q", str(self.root / "benchmarks" / "real_project_generation" / "acceptance" / "test_cli_csv_cleaner.py")], cwd=workspace, capture_output=True, timeout=60, env=env)
        hidden = "PASS" if hidden_run.returncode == 0 else "FAIL"
        status = "PASS" if passed and hidden == "PASS" else "FAIL"
        return DirectAgentResult(status, run_id, workspace, 1, int(completion.usage.get("total_tokens", 0)), int((time.perf_counter() - started) * 1000), 0, hidden)
