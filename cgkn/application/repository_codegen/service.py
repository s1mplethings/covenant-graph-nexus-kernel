from __future__ import annotations

import ast
import json
import os
import pathlib
import subprocess
import time
from typing import Any, Callable

from cgkn.application.software_project.contracts import WorkerScope
from cgkn.application.software_project.scope import ScopedFileTransaction
from cgkn.executors.llm import WORKER_SCHEMA, validate_worker_proposal
from cgkn.providers import CompletionClient, ModelRoleConfig, parse_json_object
from cgkn.application.learning import GenerationRequest, ProductionGenerationClient, canonical_hash, default_production_client

from .analyzer import compile_change_contract, snapshot_repository
from .contracts import ChangeRequest, RepositoryCodegenReceipt


class RepositoryCodegenService:
    def __init__(self, client: CompletionClient | ProductionGenerationClient, config: ModelRoleConfig, *, provider_id: str, mode: str,
                 call_authorizer: Callable[[str], None] | None = None, max_attempts: int = 2) -> None:
        if config.role != "worker" or config.model != provider_id or mode not in {"SELECTED", "SINGLE_PROVIDER_MODE"}:
            raise ValueError("repository codegen requires one frozen worker route")
        self.generation = client if isinstance(client, ProductionGenerationClient) else default_production_client(client)
        self.client, self.config, self.provider_id, self.mode = self.generation.client, config, provider_id, mode
        self.call_authorizer = call_authorizer
        if max_attempts not in {1, 2}:
            raise ValueError("repository codegen max_attempts must be 1 or 2")
        self.max_attempts = max_attempts
        self.task_class = "repository.patch"

    def as_task_class(self, task_class: str) -> "RepositoryCodegenService":
        if task_class not in {"repository.patch", "project.repair"}:
            raise ValueError("unsupported repository codegen task class")
        self.task_class = task_class
        return self

    def run(self, root: pathlib.Path | str, request: ChangeRequest) -> RepositoryCodegenReceipt:
        started = time.monotonic(); base = pathlib.Path(root).resolve(); before = snapshot_repository(base, request.change_id); contract = compile_change_contract(before, request)
        calls = repairs = 0; usage: dict[str, Any] = {}
        scope = WorkerScope(contract.allowed_paths, contract.allowed_paths, protected_paths=contract.forbidden_paths, max_actions=4, max_write_files=2, allow_create=request.change_kind.value == "FEATURE", allow_patch=True)
        transaction = ScopedFileTransaction(base, scope)
        failure = ""
        for attempt in range(self.max_attempts):
            if self.call_authorizer is not None:
                self.call_authorizer("REPAIR" if failure else "GENERATION")
            prompt = self._prompt(base, request, contract, failure)
            prompt_chars = len(json.dumps(prompt, ensure_ascii=False, sort_keys=True))
            cap = 20_000 if self.task_class == "project.repair" else 24_000
            if prompt_chars > cap:
                raise RuntimeError(f"PROMPT_PROJECTION_OVERFLOW:{prompt_chars}>{cap}")
            projection_hash = canonical_hash({"version": "production-repository-projection-v1", "task_class": self.task_class, "payload": prompt})
            generated = self.generation.generate(GenerationRequest(
                task_class=self.task_class, operation="REPAIR" if self.task_class == "project.repair" or failure else "GENERATION",
                project_id=request.change_id, capability_ref="repository.patch@1", provider_id=self.provider_id,
                system="You are a bounded existing-repository patch worker. Use exact patch_file actions for existing files. Preserve declared interfaces and never edit tests, configuration, governance, hidden acceptance, or files outside target paths. Return JSON only.",
                goal={"projection_hash": projection_hash}, contract={"change_contract_hash": canonical_hash({"allowed_paths": contract.allowed_paths, "required_interfaces": dict(contract.required_interfaces)})},
                state=prompt["current_sources"], failure_evidence={"failure": failure} if failure else {},
                schema_name="repository_patch", schema=WORKER_SCHEMA, model_config=self.config,
                allowed_actions=("patch_file", "write_file"), forbidden_actions=("tests", "configuration", "governance", "hidden_acceptance"),
                projected_prompt=prompt, prompt_projection_hash=projection_hash,
            ))
            completion = generated.completion
            calls += 1; usage = dict(completion.usage)
            proposal = validate_worker_proposal(parse_json_object(completion.text), request.change_id)
            if proposal["needs_escalation"]: failure = str(proposal["escalation_reason"]); break
            actions = proposal["actions"]
            if any(action.get("action") == "write_file" and (base / str(action.get("path"))).is_file() for action in actions):
                raise ValueError("existing repository changes must be patch-first")
            transaction.apply(actions)
            ok, failure = self._verify(base, contract)
            if ok: break
            repairs += 1
        after = snapshot_repository(base, request.change_id)
        changed = tuple(sorted(path for path in set(before.files) | set(after.files) if before.files.get(path) != after.files.get(path)))
        unrelated = tuple(path for path in changed if path not in contract.allowed_paths)
        breaks = tuple(self._interface_breaks(base, contract))
        passed = not failure and not unrelated and not breaks
        return RepositoryCodegenReceipt(request.change_id, request.change_kind.value, self.provider_id, self.mode, True, "deny", calls, repairs, changed, unrelated, breaks, passed, "PASS" if passed else "FAIL", int((time.monotonic()-started)*1000), usage)

    @staticmethod
    def _prompt(base: pathlib.Path, request: ChangeRequest, contract, failure: str) -> dict[str, Any]:
        sources = {path: (base / path).read_text(encoding="utf-8") for path in contract.read_paths if (base / path).is_file()}
        return {"node_id": request.change_id, "goal": request.goal, "change_kind": request.change_kind.value, "requirements": request.requirements, "preserved_behavior": request.preserved_behavior, "acceptance": request.acceptance, "allowed_paths": contract.allowed_paths, "required_interfaces": dict(contract.required_interfaces), "current_sources": sources, "failure_evidence": failure, "allowed_actions": ["patch_file", "write_file"]}

    @staticmethod
    def _verify(base: pathlib.Path, contract) -> tuple[bool, str]:
        for path in contract.allowed_paths:
            target = base / path
            if target.suffix == ".py" and target.is_file():
                try: ast.parse(target.read_text(encoding="utf-8"))
                except SyntaxError as exc: return False, f"syntax failure in {path}: {exc}"
        environment = os.environ.copy()
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        result = subprocess.run(["python", "-m", "pytest", "-q"], cwd=base, capture_output=True, text=True, timeout=120, env=environment)
        return (result.returncode == 0, (result.stdout + "\n" + result.stderr)[-4000:] if result.returncode else "")

    @staticmethod
    def _interface_breaks(base: pathlib.Path, contract) -> list[str]:
        breaks = []
        for path, names in contract.preserved_interfaces.items():
            target = base / path
            if not target.is_file(): breaks.append(path + ":missing"); continue
            try: tree = ast.parse(target.read_text(encoding="utf-8"))
            except SyntaxError: breaks.append(path + ":syntax"); continue
            current = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
            breaks.extend(path + ":" + name for name in names if name not in current)
        return breaks

